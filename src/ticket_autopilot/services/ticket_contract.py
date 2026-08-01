"""Deterministic Plane issue -> ``ticket-spec`` intake gate.

This module deliberately reuses :func:`ticket_autopilot.connectors.plane.fetch_issue`
for Plane I/O.  It only parses an explicitly structured Markdown description and
validates a small, dependency-free JSON Schema subset; it never invokes an Agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ticket_autopilot.connectors import plane

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "ticket-spec.schema.json"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}

_SECTION_ALIASES = {
    "goal": "goal",
    "goal (why)": "goal",
    "scope": "scope",
    "scope boundary": "scope",
    "out-of-scope": "out_of_scope",
    "out of scope": "out_of_scope",
    "out of scope (explicit non-goals)": "out_of_scope",
    "risk tier": "risk_tier",
    "risk": "risk_tier",
    "acceptance criteria": "acceptance_criteria",
    "acceptance": "acceptance_criteria",
    "verification": "verification",
    "verification method": "verification",
    "verification method (the deterministic gate)": "verification",
    "repository": "repository",
    "required checks": "required_checks",
    "constraints": "constraints",
}
_REQUIRED_SECTIONS = tuple(dict.fromkeys(_SECTION_ALIASES.values()))


class TicketContractError(ValueError):
    """A Plane issue cannot be mechanically turned into a ticket contract."""

    def __init__(self, message: str, *, code: str = "INVALID_CONTRACT", field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


def load_ticket_spec_schema() -> dict[str, Any]:
    """Load the versioned ticket-spec schema shipped with the package."""
    with _SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _check(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    """Validate exactly the JSON Schema subset used by ticket-spec.schema.json."""
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
        return

    expected = schema.get("type")
    if expected:
        if isinstance(value, bool) and expected in {"integer", "number"}:
            errors.append(f"{path}: expected {expected}, got boolean")
            return
        if not isinstance(value, _TYPES[expected]):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return

    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{path}: must contain at least {schema['minLength']} character(s)")
    if "minimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
    if "pattern" in schema and isinstance(value, str) and not re.fullmatch(schema["pattern"], value):
        errors.append(f"{path}: does not match {schema['pattern']!r}")

    if expected == "object":
        for required_key in schema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required property '{required_key}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property '{key}'")
        for key, subschema in properties.items():
            if key in value:
                _check(value[key], subschema, f"{path}.{key}", errors)

    if expected == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: must contain at least {schema['minItems']} item(s)")
        if "items" in schema:
            for index, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{index}]", errors)


def validate_ticket_spec(ticket_spec: Any) -> tuple[bool, list[str]]:
    """Return whether a candidate ticket-spec satisfies the shipped schema."""
    if not isinstance(ticket_spec, dict):
        return False, ["ticket-spec payload is not a JSON object"]
    errors: list[str] = []
    _check(ticket_spec, load_ticket_spec_schema(), "$", errors)
    return not errors, errors


def _normalise_heading(heading: str) -> str:
    heading = re.sub(r"[*_`]+", "", heading).strip().rstrip(":")
    heading = re.sub(r"^[0-9]+\.\s*", "", heading)
    return re.sub(r"\s+", " ", heading).casefold()


def _sections(description: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", description))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        canonical = _SECTION_ALIASES.get(_normalise_heading(match.group(1)))
        if not canonical:
            continue
        if canonical in result:
            raise TicketContractError(
                f"ambiguous duplicate section: {canonical}", code="AMBIGUOUS_FIELD", field=canonical
            )
        end = matches[index + 1].start() if index + 1 < len(matches) else len(description)
        body = description[match.end():end].strip()
        result[canonical] = body
    return result


def _nonempty_section(sections: dict[str, str], field: str) -> str:
    value = sections.get(field, "").strip()
    if not value:
        raise TicketContractError(f"missing required section: {field}", field=field)
    return value


def _plain(value: str) -> str:
    return re.sub(r"^[`*_\s]+|[`*_\s]+$", "", value).strip()


def _bullet_values(body: str) -> list[str]:
    values = []
    for line in body.splitlines():
        match = re.match(r"\s*[-*]\s+(?:\[[ xX]\]|[☐☑✓])?\s*(.+?)\s*$", line)
        if match and (value := _plain(match.group(1))):
            values.append(value)
    return values


def _ac_id(value: str) -> str:
    match = re.fullmatch(r"AC[-_ ]?([1-9][0-9]*)", value.strip(), flags=re.IGNORECASE)
    if not match:
        raise TicketContractError(f"invalid acceptance criterion id: {value}", field="acceptance_criteria")
    return f"AC-{match.group(1)}"


def _parse_acceptance_criteria(body: str) -> list[dict[str, str]]:
    criteria: list[dict[str, str]] = []
    for line in body.splitlines():
        match = re.match(
            r"\s*[-*]\s+(?:\[[ xX]\]|[☐☑✓])?\s*(AC[-_ ]?[1-9][0-9]*)\s*[:\-–—]\s*(.+?)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            criteria.append({"id": _ac_id(match.group(1)), "text": _plain(match.group(2))})
    if not criteria:
        raise TicketContractError(
            "acceptance_criteria requires explicit AC-<number> bullet IDs", field="acceptance_criteria"
        )
    ids = [criterion["id"] for criterion in criteria]
    if len(ids) != len(set(ids)):
        raise TicketContractError("acceptance_criteria contains duplicate IDs", field="acceptance_criteria")
    return criteria


def _first_code_or_text(value: str) -> str:
    code = re.search(r"`([^`\n]+)`", value)
    if code:
        return code.group(1).strip()
    bullet = re.fullmatch(r"\s*[-*]\s+(.+?)\s*", value, flags=re.DOTALL)
    return _plain(bullet.group(1) if bullet else value)


def _parse_verification(body: str) -> list[dict[str, str]]:
    verification: list[dict[str, str]] = []
    for line in _bullet_values(body):
        # Canonical form: "AC-1: automated: `python3 -m pytest ...`".
        match = re.match(
            r"(AC[-_ ]?[1-9][0-9]*)\s*(?::|\|)\s*"
            r"(automated|query|inspection|manual)\s*(?::|\|)\s*(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            # Also accept a labelled, equally deterministic form.
            match = re.match(
                r"(AC[-_ ]?[1-9][0-9]*)\s*:\s*type\s*=\s*"
                r"(automated|query|inspection|manual)\s*;\s*command\s*=\s*(.+)$",
                line,
                flags=re.IGNORECASE,
            )
        if not match:
            continue
        command = _first_code_or_text(match.group(3))
        if not command:
            raise TicketContractError("verification command is empty", field="verification")
        verification.append({
            "acceptance_criterion_id": _ac_id(match.group(1)),
            "type": match.group(2).casefold(),
            "command": command,
        })
    if not verification:
        raise TicketContractError(
            "verification requires AC-<number>: <type>: <command> entries", field="verification"
        )
    ids = [entry["acceptance_criterion_id"] for entry in verification]
    if len(ids) != len(set(ids)):
        raise TicketContractError("verification contains duplicate AC IDs", field="verification")
    return verification


def _parse_constraints(body: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for source_line in body.splitlines():
        bullet = re.match(r"\s*[-*]\s+(.+?)\s*$", source_line)
        if not bullet:
            continue
        # Unlike generic prose bullets, glob patterns must retain trailing '*'.
        match = re.match(r"([^:]+):\s*(.+)$", bullet.group(1))
        if not match:
            continue
        key = re.sub(r"[*`]", "", match.group(1)).strip().casefold().replace("-", "_").replace(" ", "_")
        raw_source = match.group(2).strip()
        raw = _plain(raw_source)
        if key in {"max_fix_attempts", "max_changed_files"} and re.fullmatch(r"[0-9]+", raw):
            values[key] = int(raw)
        elif key == "allow_main_push" and raw.casefold() in {"true", "false"}:
            values[key] = raw.casefold() == "true"
        elif key == "forbidden_paths":
            paths = [part.strip().strip("`") for part in raw_source.split(",")]
            if paths and all(paths):
                values[key] = paths
    missing = {"max_fix_attempts", "allow_main_push"} - values.keys()
    if missing:
        raise TicketContractError(
            "constraints must include " + ", ".join(sorted(missing)), field="constraints"
        )
    return values


def _issue_key(issue: dict[str, Any]) -> str:
    for field in ("identifier", "issue_key", "key"):
        if value := issue.get(field):
            return str(value)
    # Ticket keys are source data, never guessed from a mutable title.
    raise TicketContractError("Plane issue has no explicit issue key", field="issue_key")


def _cancelled(issue: dict[str, Any]) -> bool:
    state = issue.get("state")
    if isinstance(state, dict) and state.get("group"):
        return str(state["group"]).casefold() == "cancelled"
    values = state.values() if isinstance(state, dict) else (state,)
    return any(value is not None and str(value).casefold() in {"cancelled", "canceled"} for value in values)


def _extract_embedded_out_of_scope(scope_body: str) -> tuple[str, str] | None:
    """Split a Scope-boundary body at an explicit ``Out of scope`` label line.

    The agent-ready template nests the non-goal list inside ``## Scope boundary``
    as a labelled bullet rather than an own heading.  The split is purely
    textual: it only fires when the label literally appears in the ticket.
    """
    lines = scope_body.splitlines()
    for index, line in enumerate(lines):
        label = re.sub(r"^\s*[-*]\s+", "", line)
        if _SECTION_ALIASES.get(_normalise_heading(label)) == "out_of_scope":
            scope = "\n".join(lines[:index]).strip()
            out_of_scope = "\n".join(lines[index + 1:]).strip()
            if scope and out_of_scope:
                return scope, out_of_scope
    return None


def _single_gate_verification(body: str, criteria: list[dict[str, str]]) -> list[dict[str, str]]:
    """Expand the template's single deterministic gate to every criterion.

    The agent-ready template states one ``Type`` / ``Command or procedure`` gate
    for the whole ticket; applying that exact command to each acceptance
    criterion is a deterministic expansion, not an inference.
    """
    gate_type = "automated"
    command = ""
    for line in _bullet_values(body):
        type_match = re.match(r"(?i)type\s*[:=]\s*(.+)$", line)
        if type_match:
            raw_type = _plain(type_match.group(1)).casefold()
            for known in ("manual", "inspection", "query"):
                if known in raw_type:
                    gate_type = known
                    break
            continue
        command_match = re.match(r"(?i)command(?:\s+or\s+procedure)?\s*[:=]\s*(.+)$", line)
        if command_match and not command:
            command = _first_code_or_text(command_match.group(1))
    if not command:
        code = re.search(r"`([^`\n]+)`", body)
        command = code.group(1).strip() if code else ""
    if not command:
        raise TicketContractError(
            "verification requires AC-<number>: <type>: <command> entries", field="verification"
        )
    return [
        {"acceptance_criterion_id": criterion["id"], "type": gate_type, "command": command}
        for criterion in criteria
    ]


def map_plane_issue(issue: dict[str, Any], *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mechanically map an explicitly structured Plane issue to ticket-spec v1.0.

    No scope values are inferred: goal, scope, non-goals, acceptance criteria,
    and the verification gate always come from the issue description, and
    ``source_issue`` plus ``provenance`` retain their exact source locations.
    When ``defaults`` is provided (owner-approved relaxed intake for the
    agent-ready nine-field template), only the missing operational parameters
    are filled deterministically: repository from configuration, risk tier R1,
    required checks derived from the ticket's own verification commands, and
    the safe constraints ``max_fix_attempts=3`` / ``allow_main_push=false``.
    """
    if not isinstance(issue, dict):
        raise TicketContractError("Plane issue payload is not an object")
    # Plane v2 carries deliberately-null legacy fields.  Normalize exactly once
    # before parsing, retaining raw source/provenance on the normalized object.
    if issue.get("description_html") is not None or isinstance(issue.get("project"), dict):
        try:
            issue = plane.normalize_work_item(issue)
        except plane.PlaneNormalizationError as exc:
            raise TicketContractError(str(exc), code="V2_NORMALIZATION_FAILED", field="source_issue") from exc
    issue_id = issue.get("id")
    if not issue_id:
        raise TicketContractError("Plane issue has no id", field="source_issue.id")
    description = issue.get("description")
    if not isinstance(description, str) or not description.strip():
        raise TicketContractError("Plane issue has no description", field="description")
    title = str(issue.get("name") or issue.get("title") or "").strip()
    if not title:
        raise TicketContractError("Plane issue has no title", field="source_issue.title")

    sections = _sections(description)
    relaxed = defaults is not None
    provenance_overrides: dict[str, str] = {}
    source = str(issue.get("_description_provenance") or "description")
    if "out_of_scope" not in sections and "scope" in sections:
        embedded = _extract_embedded_out_of_scope(sections["scope"])
        if embedded:
            sections["scope"], sections["out_of_scope"] = embedded
            provenance_overrides["out_of_scope"] = f"{source}#Scope boundary>Out of scope"
    goal = _nonempty_section(sections, "goal")
    scope = _nonempty_section(sections, "scope")
    out_of_scope = _nonempty_section(sections, "out_of_scope")
    if relaxed and "risk_tier" not in sections:
        # Owner-approved default: a template ticket without an explicit tier
        # runs as R1; higher tiers must still be declared to block automation.
        risk_tier = "R1"
        provenance_overrides["risk_tier"] = "default#risk_tier"
    else:
        risk_source = _plain(_nonempty_section(sections, "risk_tier")).upper()
        risk_match = re.search(r"\bR[0-9]\b", risk_source)
        if not risk_match:
            raise TicketContractError("risk tier must be R0, R1, R2, or R3", code="UNKNOWN_RISK_TIER", field="risk_tier")
        risk_tier = risk_match.group(0)
        if risk_tier not in {"R0", "R1", "R2", "R3"}:
            raise TicketContractError("risk tier must be R0, R1, R2, or R3", code="UNKNOWN_RISK_TIER", field="risk_tier")
    acceptance_criteria = _parse_acceptance_criteria(_nonempty_section(sections, "acceptance_criteria"))
    verification_body = _nonempty_section(sections, "verification")
    try:
        verification = _parse_verification(verification_body)
    except TicketContractError as error:
        if not (relaxed and "requires AC-" in str(error)):
            raise
        verification = _single_gate_verification(verification_body, acceptance_criteria)
        provenance_overrides["verification"] = f"{source}#Verification (single gate)"
    if relaxed and "repository" not in sections:
        repository = str(defaults.get("repository") or "").strip()
        if not repository:
            raise TicketContractError("missing required section: repository", field="repository")
        provenance_overrides["repository"] = "config#repository"
    else:
        repository = _first_code_or_text(_nonempty_section(sections, "repository"))
    if relaxed and "required_checks" not in sections:
        # Derive from every gate command so a manual-typed gate still reaches
        # the clearer MANUAL_VERIFICATION block instead of a bullet-count error.
        required_checks = list(dict.fromkeys(entry["command"] for entry in verification))
        if not required_checks:
            raise TicketContractError("required_checks requires at least one bullet", field="required_checks")
        provenance_overrides["required_checks"] = f"{source}#Verification"
    else:
        required_checks = [_first_code_or_text(value) for value in _bullet_values(
            _nonempty_section(sections, "required_checks")
        )]
        if not required_checks:
            raise TicketContractError("required_checks requires at least one bullet", field="required_checks")
    if relaxed and "constraints" not in sections:
        constraints = {"max_fix_attempts": 3, "allow_main_push": False}
        provenance_overrides["constraints"] = "default#constraints"
    else:
        constraints = _parse_constraints(_nonempty_section(sections, "constraints"))

    criterion_ids = {criterion["id"] for criterion in acceptance_criteria}
    verification_ids = {entry["acceptance_criterion_id"] for entry in verification}
    if criterion_ids != verification_ids:
        raise TicketContractError(
            "every acceptance criterion must have exactly one verification entry", field="verification"
        )

    source_issue = {
        "provider": "plane", "id": str(issue_id), "key": _issue_key(issue),
        "title": title, "description": description,
    }
    if isinstance(issue.get("raw_source"), dict):
        source_issue["raw_source"] = issue["raw_source"]
    return {
        "schema_version": "1.0",
        "issue_key": _issue_key(issue),
        "source_issue": source_issue,
        "goal": goal,
        "scope": scope,
        "out_of_scope": out_of_scope,
        "risk_tier": risk_tier,
        "acceptance_criteria": acceptance_criteria,
        "verification": verification,
        "repository": repository,
        "required_checks": required_checks,
        "constraints": constraints,
        "provenance": {**{
            "goal": f"{source}#Goal",
            "scope": f"{source}#Scope",
            "out_of_scope": f"{source}#Out-of-scope",
            "risk_tier": f"{source}#Risk Tier",
            "acceptance_criteria": f"{source}#Acceptance Criteria",
            "verification": f"{source}#Verification",
            "repository": f"{source}#Repository",
            "required_checks": f"{source}#Required Checks",
            "constraints": f"{source}#Constraints",
        }, **provenance_overrides},
    }


def _blocked(status: str, error: TicketContractError | str) -> dict[str, Any]:
    if isinstance(error, TicketContractError):
        entry = {"code": error.code, "message": str(error)}
        if error.field:
            entry["field"] = error.field
    else:
        entry = {"code": "SCHEMA_INVALID", "message": str(error)}
    return {"status": status, "ticket_spec": None, "errors": [entry]}


def readiness_errors(issue: dict[str, Any]) -> list[str]:
    """Check ticket-owned operational evidence beyond the nine schema fields.

    This is deliberately separate from the reusable v1 ticket-spec schema: it
    applies the AIO-18 intake/Planner boundary without retroactively changing
    AIO-10 callers that only need schema validation.
    """
    description = str(issue.get("description") or "").casefold()
    checks = {
        "impact closure": (("impact closure", "影响闭包"),),
        "callers and consumers": (("caller",), ("consumer",)),
        "triggered guards": (("trigger",), ("guard",)),
        "executable dependencies": (("dependenc",),),
        "behavioral acceptance criteria": (("given",), ("when",), ("then",)),
        "upstream observed semantics": (("observ",), ("checked-at",), ("semantic mapping",)),
        "global serial resources": (("serial",), ("127.0.0.1:8765",)),
    }
    missing = [name for name, groups in checks.items()
               if not all(any(term in description for term in alternatives) for alternatives in groups)]
    return [f"missing ticket readiness evidence: {name}" for name in missing]


def preflight_plane_issue(issue: dict[str, Any], *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a Plane issue without spawning Planner, Executor, or QA Agents."""
    if not isinstance(issue, dict):
        return _blocked("BLOCKED_REQUIREMENTS", TicketContractError("Plane issue payload is not an object"))
    if _cancelled(issue):
        return _blocked("BLOCKED_NEEDS_HUMAN", TicketContractError(
            "Plane issue is cancelled and cannot enter development", code="ISSUE_CANCELLED", field="state"
        ))
    try:
        ticket_spec = map_plane_issue(issue, defaults=defaults)
    except TicketContractError as error:
        # Ambiguous/unknown v2 source semantics need a PM decision; incomplete
        # contract fields are requirements failures before any Agent is invoked.
        status = "BLOCKED_NEEDS_HUMAN" if error.code in {"AMBIGUOUS_FIELD", "V2_NORMALIZATION_FAILED"} or error.field == "risk_tier" else "BLOCKED_REQUIREMENTS"
        return _blocked(status, error)

    valid, errors = validate_ticket_spec(ticket_spec)
    if not valid:
        return _blocked("BLOCKED_REQUIREMENTS", "; ".join(errors))
    if ticket_spec["risk_tier"] not in {"R0", "R1"}:
        return _blocked("BLOCKED_NEEDS_HUMAN", TicketContractError(
            f"risk tier {ticket_spec['risk_tier']} is not eligible for automated development",
            code="RISK_NOT_AUTOMATABLE", field="risk_tier",
        ))
    if any(item["type"] == "manual" for item in ticket_spec["verification"]):
        return _blocked("BLOCKED_REQUIREMENTS", TicketContractError(
            "manual verification cannot enter the automated ticket loop",
            code="MANUAL_VERIFICATION", field="verification",
        ))
    return {"status": "READY", "ticket_spec": ticket_spec, "errors": []}


def fetch_and_preflight_plane_issue(issue_id: str, **connector_options: Any) -> dict[str, Any]:
    """Reuse the AIO-8 Plane Connector's authenticated, rate-limited read path."""
    return preflight_plane_issue(plane.fetch_issue(issue_id, **connector_options))


# Short aliases keep the pure mapper and connector-backed gate convenient for callers.
preflight = preflight_plane_issue
prepare_ticket = preflight_plane_issue

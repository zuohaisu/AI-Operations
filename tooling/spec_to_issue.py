#!/usr/bin/env python3
"""Offline contract validator for the project spec-to-plane-issue skill.

This tool deliberately has no HTTP client and never reads credentials.  Its default
(and only) execution mode renders validated Plane issue drafts to stdout.  The skill
owns the separately confirmed, human-supervised Plane REST apply procedure.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

FIELDS: Sequence[Tuple[str, str]] = (
    ("Title", "Title"),
    ("Goal (why)", "Goal (why)"),
    ("Scope boundary", "Scope boundary"),
    ("Acceptance criteria", "Acceptance criteria"),
    ("Verification method (the deterministic gate)", "Verification method"),
    ("Dependencies", "Dependencies"),
    ("Definition of Done", "Definition of Done"),
    ("Risk & rollback", "Risk & rollback"),
    ("Human touchpoints", "Human touchpoints"),
)

# Kept in the executable contract so callers can inspect the exact Plane behavior
# before an explicitly confirmed apply.  This offline tool never sends these calls.
PLANE_REST_CONTRACT = {
    "base_url": "${PLANE_API_BASE_URL:-https://api.plane.so/api/v1}",
    "auth_header": "X-Api-Key: $PLANE_API_KEY",
    "create_work_item": {
        "method": "POST",
        "path": "/projects/{project_id}/work-items/",
        "effective_fields": ["name", "description_html", "priority", "assignees"],
        "ignored_on_create": ["state_id", "label_ids", "cycle_id"],
    },
    "state_and_labels": {
        "method": "PATCH",
        "path": "/work-items/{work_item_id}/",
        "body": {"state": "<state_id>", "labels": ["<label_id>"]},
        "do_not_use": ["state_id", "label_ids"],
    },
    "cycle_membership": {
        "method": "POST",
        "path": "/cycles/{cycle_id}/cycle-issues/",
        "body": {"issues": ["<work_item_id>"]},
        "do_not_use": ["issue_ids", "work_item_ids"],
    },
}

PLACEHOLDER_RE = re.compile(r"<[^>]+>|\b(?:TBD|TODO|N/A)\b", re.IGNORECASE)
RUNNABLE_COMMAND_RE = re.compile(
    r"^(?:python(?:3)?|pytest|npm|pnpm|yarn|make|just|bash|sh|git|grep|rg|find|test|curl|docker|go|cargo|java|gradle|mvn|node)\b|^(?:\./|/)"
)


class ContractError(ValueError):
    """A draft cannot enter Plane or In Progress."""


def _split_drafts(text: str) -> List[str]:
    """Split optional '# Ticket ...' / '# Issue ...' groups, retaining one draft."""
    starts = list(re.finditer(r"(?m)^#\s+(?:Ticket|Issue)\b.*$", text))
    if not starts:
        return [text]
    drafts = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        drafts.append(text[match.end() : end].strip())
    return drafts


def _section_pattern(number: int, heading: str) -> re.Pattern:
    # Existing template headings contain explanatory parentheticals; accept them.
    return re.compile(
        r"(?m)^##\s+" + str(number) + r"\.\s+" + re.escape(heading) + r"(?:\s*\([^\n]*\))?\s*$"
    )


def parse_draft(text: str) -> Dict[str, str]:
    matches = []
    for number, (output_heading, required_prefix) in enumerate(FIELDS, start=1):
        field_matches = list(_section_pattern(number, required_prefix).finditer(text))
        if not field_matches:
            raise ContractError("missing required field: {}".format(output_heading))
        if len(field_matches) > 1:
            raise ContractError(
                "spec contains multiple independently shippable units; apply the 工单组拆分规则 "
                "and separate drafts with # Ticket <n>"
            )
        match = field_matches[0]
        matches.append((match.start(), match.end(), output_heading))

    if [item[0] for item in matches] != sorted(item[0] for item in matches):
        raise ContractError("required fields must appear in template order (1 through 9)")

    fields: Dict[str, str] = {}
    for index, (_, body_start, output_heading) in enumerate(matches):
        body_end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body or PLACEHOLDER_RE.search(body):
            raise ContractError("{} is empty or contains a placeholder".format(output_heading))
        fields[output_heading] = body
    return fields


def _has_content(value: str) -> bool:
    cleaned = re.sub(r"(?m)^\s*[-*]\s*(?:\*\*)?[^\n:]+:\s*(?:\*\*)?\s*$", "", value)
    cleaned = re.sub(r"(?m)^\s*[-*]\s*", "", cleaned).strip()
    return bool(cleaned) and cleaned.lower() not in {"none", "n/a", "tbd", "todo", "-"} and not bool(PLACEHOLDER_RE.search(cleaned))


def validate_draft(fields: Dict[str, str]) -> None:
    scope = fields["Scope boundary"]
    in_scope = re.search(r"(?is)\*\*In scope:\*\*(.*?)(?=\*\*Out of scope)", scope)
    out_scope = re.search(r"(?is)\*\*Out of scope\s*\(explicit non-goals\):\*\*(.*)$", scope)
    if not out_scope or not _has_content(out_scope.group(1)):
        raise ContractError("Scope boundary requires a non-empty Out of scope (explicit non-goals) list")
    if not in_scope or not _has_content(in_scope.group(1)):
        raise ContractError("Scope boundary requires a non-empty In scope list")

    criteria = re.findall(r"(?m)^\s*-\s*\[.\]\s+(.+)$", fields["Acceptance criteria"])
    if not criteria:
        raise ContractError("Acceptance criteria requires at least one checkbox pass/fail statement")
    for criterion in criteria:
        given_when_then = re.search(r"(?i)\bgiven\b.*\bwhen\b.*\bthen\b", criterion)
        explicit_outcome = re.search(r"(?i)\b(?:pass|fail)\b", criterion)
        if not (given_when_then or explicit_outcome):
            raise ContractError(
                "Acceptance criterion is not measurable (use Given/When/Then or explicit pass/fail): {}".format(criterion)
            )

    verification = fields["Verification method (the deterministic gate)"]
    commands = re.findall(r"`([^`\n]+)`", verification)
    if not any(
        command.strip() and not PLACEHOLDER_RE.search(command) and RUNNABLE_COMMAND_RE.search(command.strip())
        for command in commands
    ):
        raise ContractError("Verification method requires an exact runnable command in backticks")

    done = re.findall(r"(?m)^\s*-\s*\[.\]\s+.+$", fields["Definition of Done"])
    if not done:
        raise ContractError("Definition of Done requires a checkbox list")

    risk = fields["Risk & rollback"]
    if not re.search(r"(?im)^\s*-\s*Risk:\s*\S+", risk) or not re.search(r"(?im)^\s*-\s*Rollback:\s*\S+", risk):
        raise ContractError("Risk & rollback requires concrete Risk and Rollback entries")

    touchpoints = fields["Human touchpoints"]
    for label in ("Trigger", "Gate", "Escalation"):
        if not re.search(r"(?im)^\s*-\s*{}:\s*\S+".format(label), touchpoints):
            raise ContractError("Human touchpoints requires a concrete {} entry".format(label))


def render_draft(fields: Dict[str, str], index: int, multiple: bool) -> str:
    lines: List[str] = []
    if multiple:
        lines.extend(["# Ticket {}".format(index), ""])
    for number, (output_heading, _) in enumerate(FIELDS, start=1):
        lines.extend(["## {}. {}".format(number, output_heading), fields[output_heading], ""])
    return "\n".join(lines).rstrip() + "\n"


def validate_and_render(source: str) -> str:
    drafts = _split_drafts(source)
    if not drafts or any(not draft.strip() for draft in drafts):
        raise ContractError("spec contains an empty ticket group")
    rendered = []
    for index, draft in enumerate(drafts, start=1):
        fields = parse_draft(draft)
        validate_draft(fields)
        rendered.append(render_draft(fields, index, len(drafts) > 1))
    return "\n".join(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and render offline nine-field Plane issue drafts.")
    parser.add_argument("--spec", type=Path, required=True, help="Markdown draft(s) using the authoritative nine-field template")
    parser.add_argument("--dry-run", action="store_true", help="Explicit preview mode (also the default; never uses the network)")
    parser.add_argument("--assert", dest="assert_contract", action="store_true", help="Exit 0 only if every draft passes the hard contract gate")
    parser.add_argument("--output", type=Path, help="Write the rendered Markdown preview to this local file")
    parser.add_argument("--show-plane-contract", action="store_true", help="Print the required Plane REST sequence; never sends it")
    parser.add_argument("--apply", action="store_true", help="Rejected: this offline validator cannot write Plane")
    parser.add_argument("--confirm", help="Reserved for the skill's human-confirmed apply procedure")
    args = parser.parse_args()

    if args.apply:
        print(
            "BLOCKED: this offline validator never writes Plane. Use the skill's apply procedure only after explicit human confirmation.",
            file=sys.stderr,
        )
        return 2
    if args.confirm:
        print("BLOCKED: --confirm is valid only with the skill's human-supervised apply procedure.", file=sys.stderr)
        return 2

    try:
        source = args.spec.read_text(encoding="utf-8")
        rendered = validate_and_render(source)
    except (OSError, ContractError) as error:
        print("BLOCKED: {}".format(error), file=sys.stderr)
        return 1

    if args.show_plane_contract:
        print(json.dumps(PLANE_REST_CONTRACT, indent=2))
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    if args.assert_contract:
        print("PASS: {} validated ticket draft(s); no network access attempted.".format(len(_split_drafts(source))), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

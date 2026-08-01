"""Multi-provider read-only Planner adapter for Web Prepare (AIO-23).

``build_planner`` returns a callable matching ``PromptResolver.prepare``'s
``planner(context=..., missing_roles=...)`` contract.  The provider is read
from the saved planner profile at call time and invoked read-only through
``AgentCatalog.build_agent`` + ``drivers.cli_call``.  Every failure is
classified with a stable ``code`` so the resolver's hard-break metadata stays
diagnosable without re-running the CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from ticket_autopilot.engine import drivers
from ticket_autopilot.services.agent_catalog import AgentCatalog, CatalogError

PLANNER_UNCONFIGURED = "PLANNER_UNCONFIGURED"
PLANNER_CLI_UNAVAILABLE = "PLANNER_CLI_UNAVAILABLE"
PLANNER_CLI_FAILED = "PLANNER_CLI_FAILED"
PLANNER_OUTPUT_INVALID = "PLANNER_OUTPUT_INVALID"

PLANNER_SYSTEM = """You are the Planner for a ticket-driven delivery loop. \
Using only read-only inspection of the repository, write the requested role \
Prompts for the ticket described in the input context.
Reply with ONLY one JSON object whose keys are exactly the requested roles \
("dev" and/or "acceptance") and whose values are complete Markdown Prompts.
Every Prompt MUST:
- open with the immediate action envelope: its first line starts with \
"立即执行" (or "Execute immediately");
- name the ticket issue key and the repository path from the context;
- require diff attribution for every change and a clean (non-dirty) worktree;
- state the conditional visual evidence gate ("visual");
- for "dev": state the Developer role boundary;
- for "acceptance": state the independent read-only QA boundary, require review \
of Controller-supplied deterministic command evidence, and explicitly prohibit \
rerunning pytest or commands that write caches, bytecode, or temporary files.
Do not wrap the JSON in Markdown fences and do not add commentary."""


class PlannerAdapterError(RuntimeError):
    """A Planner invocation failed; ``code`` classifies the failure."""

    def __init__(self, code: str, message: str, profile: dict[str, str] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.profile = dict(profile or {})


def _profile_summary(profile: Any) -> dict[str, str]:
    profile = profile if isinstance(profile, dict) else {}
    return {key: str(profile.get(key, "") or "") for key in ("provider", "model", "reasoning")}


def _parse_planner_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlannerAdapterError(PLANNER_OUTPUT_INVALID, f"Planner output is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PlannerAdapterError(PLANNER_OUTPUT_INVALID, "Planner output is not a JSON object")
    return value


def build_planner(
    settings: Any,
    repository: str | Path,
    catalog: AgentCatalog,
    *,
    cli_call: Callable[..., Any] = drivers.cli_call,
) -> Callable[..., dict[str, str]]:
    """Build the PromptResolver-compatible Planner callable."""
    repository = Path(repository).resolve()

    def planner(
        *,
        context: dict[str, Any],
        missing_roles: tuple[str, ...],
        process_observer: Callable[[str, object], None] | None = None,
    ) -> dict[str, str]:
        profile = settings.load(redacted=False)["agents"].get("planner")
        summary = _profile_summary(profile)
        if not summary["provider"]:
            raise PlannerAdapterError(PLANNER_UNCONFIGURED, "no Planner provider is configured", summary)
        try:
            entry = catalog.provider(summary["provider"])
        except CatalogError as exc:
            raise PlannerAdapterError(PLANNER_UNCONFIGURED, str(exc), summary) from exc
        if not entry["available"]:
            raise PlannerAdapterError(PLANNER_CLI_UNAVAILABLE, entry["reason"] or "provider is unavailable", summary)
        try:
            agent = catalog.build_agent(
                profile, role="planner", cwd=str(repository), allowed_roots=[str(repository)],
                system=PLANNER_SYSTEM,
            )
        except CatalogError as exc:
            raise PlannerAdapterError(PLANNER_UNCONFIGURED, str(exc), summary) from exc

        output_path: str | None = None
        if "argv" in agent:
            # codex exec mixes progress onto stdout; -o captures only the final
            # message, keeping JSON parsing deterministic.
            descriptor, output_path = tempfile.mkstemp(prefix="planner-last-message-", suffix=".txt")
            os.close(descriptor)
            argv = agent["argv"]
            agent = {**agent, "argv": [*argv[:-1], "-o", output_path, argv[-1]]}
        if process_observer is not None:
            agent = {**agent, "process_observer": process_observer}
        inputs = {
            "requested_roles": ", ".join(missing_roles),
            "context": json.dumps(context, ensure_ascii=False, sort_keys=True),
        }
        try:
            raw = cli_call(agent, inputs, {"agent": "planner"}, str(repository))
            if output_path is not None:
                try:
                    raw = Path(output_path).read_text(encoding="utf-8")
                except OSError as exc:
                    raise PlannerAdapterError(
                        PLANNER_OUTPUT_INVALID, "Planner CLI produced no output message file", summary,
                    ) from exc
        except PlannerAdapterError:
            raise
        except Exception as exc:
            raise PlannerAdapterError(PLANNER_CLI_FAILED, (str(exc) or type(exc).__name__)[:500], summary) from exc
        finally:
            if output_path is not None:
                Path(output_path).unlink(missing_ok=True)

        try:
            parsed = _parse_planner_output(raw)
        except PlannerAdapterError as exc:
            exc.profile = summary
            raise
        missing = [role for role in missing_roles
                   if not isinstance(parsed.get(role), str) or not parsed[role].strip()]
        if missing:
            raise PlannerAdapterError(
                PLANNER_OUTPUT_INVALID, f"Planner output lacks non-empty Prompts for: {missing}", summary,
            )
        return {role: parsed[role] for role in missing_roles}

    return planner

"""Independent QA connector: call the QA CLI, validate the verdict, gate the loop.

Three steps (AIO-7): invoke the QA agent read-only via drivers.cli_call ->
parse the qa-verdict JSON -> deterministic schema validation. Mapping to the
engine decision (spec §2.4, no false success):

  schema-valid verdict == "PASS"        -> {"decision": "accept", "verdict": ...}
  schema-valid verdict FAIL / BLOCKED   -> {"decision": "reject", "verdict": ...}
  CLI failure / parse failure / invalid -> {"decision": "reject", "verdict": BLOCKED}

Only a schema-valid PASS may ever produce accept.
"""

from __future__ import annotations

import json
import os

from ..engine import drivers
from ..schemas.qa_verdict import validate_verdict

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QA_SYSTEM_PROMPT = """You are the independent QA Verifier. Using only read-only \
inspection, verify the execution result against the plan and the ticket context \
(acceptance criteria, diff, test evidence). You must not modify code or add tests. \
The Controller has already run every declared deterministic command and supplied \
its exit code, stdout, and stderr. Inspect that evidence independently, but do not \
rerun pytest or any command that writes caches, bytecode, or temporary files. A \
missing local virtual environment is not a blocker when the supplied Controller \
evidence is complete and passing. This QA gate runs before the Controller commit: \
ticket-attributable changed files and the absence of the final commit are expected \
at this stage. Do not require a commit or clean worktree for QA PASS; verify the \
proposed diff, and leave commit creation plus the final clean-worktree check to \
the downstream Controller step.
Reply with ONLY a qa-verdict JSON object with exactly these fields:
schema_version ("1.0"), issue_key, run_id, qa_attempt (integer),
verdict ("PASS"|"FAIL"|"BLOCKED"),
acceptance_criteria (array of {id, status: "PASS"|"FAIL"|"BLOCKED", evidence: [strings]}),
findings (array of {id, severity: "blocker"|"major"|"minor", type,
acceptance_criterion_id, summary, evidence, required_fix}) where evidence is a
JSON OBJECT (not a string/array), e.g. {"file": "...", "observed": "...", "expected": "..."},
non_blocking_comments (array), recommended_next_state."""

# Engine policy requires every CLI invocation to declare read-only. The
# restricted tool set is a second boundary for qodercli's non-interactive mode.
# --allowed-tools auto-approves ONLY the read tools in non-interactive -p mode.
QA_AGENT = {
    "driver": "cli",
    "command": "qodercli",
    "cwd": "sandbox",
    "permission_mode": "read-only",
    "tools": ["Read", "Glob", "Grep"],
    "tools_flag": "--tools",
    "tools_as_args": True,
    "extra_args": ["--allowed-tools", "Read,Glob,Grep", "--no-session-persistence"],
    "expect": "json",
    "system": QA_SYSTEM_PROMPT,
}


def _blocked_verdict(
    reason: str, raw: object = None, *, issue_key: str = "UNKNOWN", run_id: str = "UNKNOWN", qa_attempt: int = 0,
) -> dict:
    return {
        "schema_version": "1.0",
        "issue_key": issue_key,
        "run_id": run_id,
        "qa_attempt": qa_attempt,
        "verdict": "BLOCKED",
        "acceptance_criteria": [],
        "findings": [{
            "id": "QA-BLOCKED",
            "severity": "blocker",
            "type": "QA_OUTPUT_INVALID",
            "acceptance_criterion_id": "N/A",
            "summary": reason,
            "evidence": {"raw": repr(raw)[:500]},
            "required_fix": "QA agent must emit a schema-valid qa-verdict JSON object.",
        }],
        "non_blocking_comments": [],
        "recommended_next_state": "BLOCKED_NEEDS_HUMAN",
    }


def run_qa(plan=None, result=None, ticket_context=None, agent=None,
           engine_root=None, *, ticket_spec=None, diff=None, test_evidence=None,
           run_id=None, qa_attempt=None) -> dict:
    agent = agent or QA_AGENT
    engine_root = engine_root or _PKG_ROOT
    issue_key = (ticket_spec or {}).get("issue_key", "UNKNOWN")
    effective_run_id = run_id or "UNKNOWN"
    effective_attempt = qa_attempt if isinstance(qa_attempt, int) else 0
    inputs = {
        # AIO-13 passes the unmodified input contract, base-to-head Diff, and
        # deterministic command evidence.  Legacy Engine use remains supported.
        "ticket_context": ticket_context or ticket_spec or "(no ticket context provided yet — AIO-8 fills this)",
        "ticket_spec": ticket_spec,
        "base_to_head_diff": diff,
        "test_evidence": test_evidence,
        "run_id": effective_run_id,
        "qa_attempt": effective_attempt,
        "plan": plan,
        "result": result,
    }

    try:
        raw = drivers.cli_call(agent, inputs, {"agent": "verifier"}, engine_root)
    except Exception as exc:  # CLI crash / non-zero exit / timeout / bad JSON
        return {"decision": "reject", "verdict": _blocked_verdict(
            f"QA CLI failed: {exc}", issue_key=issue_key, run_id=effective_run_id,
            qa_attempt=effective_attempt,
        )}

    verdict = raw
    if isinstance(verdict, str):
        try:
            verdict = json.loads(verdict)
        except json.JSONDecodeError:
            return {"decision": "reject", "verdict": _blocked_verdict(
                "QA output is not JSON", raw, issue_key=issue_key,
                run_id=effective_run_id, qa_attempt=effective_attempt,
            )}

    valid, errors = validate_verdict(verdict)
    if not valid:
        return {"decision": "reject",
                "verdict": _blocked_verdict(
                    f"qa-verdict schema validation failed: {'; '.join(errors)}", verdict,
                    issue_key=issue_key, run_id=effective_run_id, qa_attempt=effective_attempt)}

    if verdict["verdict"] == "PASS":
        # §9.3: PASS requires every AC to pass and no blocker/major finding.
        failed_acs = [ac["id"] for ac in verdict["acceptance_criteria"]
                      if ac["status"] != "PASS"]
        severe = [f["id"] for f in verdict["findings"]
                  if f["severity"] in ("blocker", "major")]
        if failed_acs or severe:
            return {"decision": "reject",
                    "verdict": _blocked_verdict(
                        "PASS verdict is self-contradictory: "
                        f"non-PASS acceptance criteria {failed_acs}, "
                        f"blocker/major findings {severe}", verdict,
                        issue_key=issue_key, run_id=effective_run_id, qa_attempt=effective_attempt)}

    decision = "accept" if verdict["verdict"] == "PASS" else "reject"
    return {"decision": decision, "verdict": verdict}

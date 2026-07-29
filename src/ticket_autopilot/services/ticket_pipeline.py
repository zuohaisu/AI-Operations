"""Ordered, evidence-gated glue for one disposable ticket Run.

This is intentionally not a second Engine or a product CLI.  It composes the
existing ticket contract, RunManager, deterministic verifier, independent QA,
and Plane/GitHub connectors at the capability gap where their ordering and
state semantics must be deterministic.

All external collaborators are injected so integration tests have no network or
agent dependency.  The on-disk pipeline state is an idempotency ledger: a
completed run returns its retained result, and a created PR is never created a
second time while retrying a later Plane write.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from ticket_autopilot.connectors import github, plane
from ticket_autopilot.schemas.qa_verdict import validate_verdict
from ticket_autopilot.services.development_verifier import VERIFIED, DevelopmentVerifier
from ticket_autopilot.services.run_manager import RunManager, RunRecord
from ticket_autopilot.services.ticket_contract import fetch_and_preflight_plane_issue

PIPELINE_STATE_FILENAME = "ticket-pipeline-state-v1.json"
MAX_FIX_ATTEMPTS = 2

BLOCKED_QA_EXHAUSTED = "BLOCKED_QA_EXHAUSTED"
BLOCKED_QA_BLOCKED = "BLOCKED_QA_BLOCKED"
BLOCKED_QA_INVALID = "BLOCKED_QA_INVALID"
BLOCKED_QA_TIMEOUT = "BLOCKED_QA_TIMEOUT"
BLOCKED_QA_EVIDENCE = "BLOCKED_QA_EVIDENCE"
BLOCKED_DETERMINISTIC_VERIFICATION = "BLOCKED_DETERMINISTIC_VERIFICATION"
BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
SUCCESS = "IN_REVIEW"

_TERMINAL = {
    SUCCESS,
    BLOCKED_QA_EXHAUSTED,
    BLOCKED_QA_BLOCKED,
    BLOCKED_QA_INVALID,
    BLOCKED_QA_TIMEOUT,
    BLOCKED_QA_EVIDENCE,
    BLOCKED_DETERMINISTIC_VERIFICATION,
    BLOCKED_ENVIRONMENT,
}


class PipelineError(RuntimeError):
    """A prerequisite or injected stage cannot be safely completed."""


class TicketPipeline:
    """Compose one ticket Run in the only permitted stage order.

    ``planner`` and ``executor`` are deliberately injected adapters for the
    existing Engine/agent invocation boundary.  The pipeline owns no agent
    policy; RunManager and Engine guardrails still own worktree and permission
    enforcement.  ``verifier`` is normally :class:`DevelopmentVerifier`; ``qa``
    normally wraps :func:`connectors.qa.run_qa`.
    """

    def __init__(
        self,
        run_manager: RunManager,
        *,
        planner: Callable[..., Any],
        executor: Callable[..., Any],
        verifier: DevelopmentVerifier | Callable[[RunRecord], dict[str, Any]],
        qa: Callable[..., Any],
        plane_update: Callable[..., dict[str, Any]] | None = None,
        github_create_pr: Callable[..., dict[str, Any]] | None = None,
        diff_provider: Callable[[RunRecord, dict[str, Any]], str] | None = None,
        base_branch: str | None = None,
        max_fix_attempts: int = MAX_FIX_ATTEMPTS,
    ):
        if max_fix_attempts != MAX_FIX_ATTEMPTS:
            # AIO-13's contract is deliberately fixed.  A later ticket can make
            # this a versioned product policy rather than silently changing it.
            raise ValueError(f"max_fix_attempts must be {MAX_FIX_ATTEMPTS}")
        self.run_manager = run_manager
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.qa = qa
        self.plane_update = plane_update or _update_plane
        self.github_create_pr = github_create_pr or github.create_pr
        self.diff_provider = diff_provider or _base_to_head_diff
        self.base_branch = base_branch
        self.max_fix_attempts = max_fix_attempts

    def run_from_plane(self, issue_id: str, **plane_options: Any) -> dict[str, Any]:
        """Read/preflight through the existing Plane connector before any agent."""
        preflight = fetch_and_preflight_plane_issue(issue_id, **plane_options)
        if preflight["status"] != "READY":
            return {
                "status": preflight["status"],
                "success": False,
                "run_id": None,
                "preflight": preflight,
            }
        return self.run(preflight["ticket_spec"], plane_issue_id=issue_id)

    def run(
        self,
        ticket_spec: dict[str, Any],
        *,
        plane_issue_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Run plan -> execute -> verify -> QA -> Draft PR/Plane state safely."""
        record = self.run_manager.create_run(ticket_spec, run_id=run_id) if run_id else self.run_manager.create_run(ticket_spec)
        return self.run_existing(record, ticket_spec=ticket_spec, plane_issue_id=plane_issue_id)

    def run_existing(
        self,
        run: RunRecord | str,
        *,
        ticket_spec: dict[str, Any] | None = None,
        plane_issue_id: str | None = None,
    ) -> dict[str, Any]:
        """Continue an owned Run from its ledger without repeating side effects."""
        record = self.run_manager.load_run(run if isinstance(run, str) else run.run_id)
        if ticket_spec is None:
            ticket_spec = json.loads((Path(record.artifact_dir) / "ticket-spec.json").read_text(encoding="utf-8"))
        state = self._load_state(record)
        if state.get("status") in _TERMINAL:
            return state["result"]

        try:
            plan = state.get("plan")
            if plan is None:
                plan = self.planner(ticket_spec=ticket_spec, run=record)
                state["plan"] = plan
                self._save_state(record, state)

            fix_attempt = int(state.get("fix_attempt", 0))
            findings = state.get("findings")
            while True:
                # ``findings`` is the unmodified QA array; no summary, plan, or
                # inferred diagnosis is added to a narrow repair input.
                execution = self.executor(
                    ticket_spec=ticket_spec, plan=plan, run=record, findings=findings,
                )
                state["execute_count"] = int(state.get("execute_count", 0)) + 1
                self._save_state(record, state)

                evidence = self._verify(record)
                if not _verified_evidence(evidence):
                    return self._blocked(
                        record, state, plane_issue_id, BLOCKED_DETERMINISTIC_VERIFICATION,
                        "deterministic verification did not produce eligible evidence",
                        evidence=evidence,
                    )

                try:
                    diff = self.diff_provider(record, evidence)
                except Exception as exc:
                    return self._blocked(
                        record, state, plane_issue_id, BLOCKED_QA_EVIDENCE,
                        f"base-to-head Diff is unavailable: {exc}", evidence=evidence,
                    )
                if not isinstance(diff, str) or not diff.strip():
                    return self._blocked(
                        record, state, plane_issue_id, BLOCKED_QA_EVIDENCE,
                        "base-to-head Diff evidence is missing", evidence=evidence,
                    )

                qa_attempt = int(state.get("qa_attempt", 0)) + 1
                try:
                    qa_output = self.qa(
                        ticket_spec=ticket_spec,
                        diff=diff,
                        test_evidence=evidence,
                        run_id=record.run_id,
                        qa_attempt=qa_attempt,
                        plan=plan,
                        execution=execution,
                    )
                except TimeoutError as exc:
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_TIMEOUT, str(exc), evidence=evidence)
                except Exception as exc:
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_BLOCKED, f"QA invocation failed: {exc}", evidence=evidence)

                verdict, invalid_reason = _normalise_qa_output(qa_output)
                if invalid_reason:
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_INVALID, invalid_reason, evidence=evidence)
                assert verdict is not None
                state["qa_attempt"] = qa_attempt
                state["last_qa_verdict"] = verdict
                self._save_qa_verdict(record, qa_attempt, verdict)
                self._save_state(record, state)

                evidence_reason = _qa_evidence_error(verdict, ticket_spec, record, qa_attempt)
                if evidence_reason:
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_EVIDENCE, evidence_reason, evidence=evidence)
                if verdict["verdict"] == "BLOCKED":
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_BLOCKED, "QA returned BLOCKED", evidence=evidence)
                if verdict["verdict"] == "PASS":
                    return self._publish(record, state, ticket_spec, plane_issue_id, evidence, verdict)

                # FAIL has exactly two possible narrow repair attempts.  The
                # third QA failure is exhaustion, never another execute/PR.
                if fix_attempt >= self.max_fix_attempts:
                    return self._blocked(record, state, plane_issue_id, BLOCKED_QA_EXHAUSTED, "QA fix attempts exhausted", evidence=evidence)
                findings = verdict["findings"]
                state["findings"] = findings
                fix_attempt += 1
                state["fix_attempt"] = fix_attempt
                self._save_state(record, state)
        except Exception as exc:
            return self._blocked(record, state, plane_issue_id, BLOCKED_ENVIRONMENT, f"pipeline stage failed: {exc}")

    def _verify(self, record: RunRecord) -> dict[str, Any]:
        if isinstance(self.verifier, DevelopmentVerifier):
            return self.verifier.verify(record)
        return self.verifier(record)

    def _publish(self, record, state, ticket_spec, plane_issue_id, evidence, verdict):
        summary = _summary(record, evidence, verdict, state.get("pr"))
        try:
            if "pr" not in state:
                state["pr"] = self.github_create_pr(
                    repo=ticket_spec["repository"],
                    base=self.base_branch or record.base_branch,
                    head=record.branch,
                    title=f"{ticket_spec['issue_key']}: {ticket_spec['goal']}",
                    body=summary,
                    draft=True,
                )
                self._save_state(record, state)
        except Exception as exc:
            return self._blocked(record, state, plane_issue_id, BLOCKED_ENVIRONMENT, f"Draft PR creation failed: {exc}", evidence=evidence)
        try:
            summary = _summary(record, evidence, verdict, state["pr"])
            if plane_issue_id and not state.get("plane_in_review"):
                state["plane_in_review"] = self.plane_update(
                    plane_issue_id, state="In Review", summary=summary,
                )
                self._save_state(record, state)
        except Exception as exc:
            # Do not issue a second Plane write after its first write failed;
            # retained local evidence is the authoritative failure record.
            return self._environment_failure(record, state, f"Plane In Review update failed: {exc}", evidence)

        result = {
            "status": SUCCESS,
            "success": True,
            "run_id": record.run_id,
            "pr": state["pr"],
            "qa_verdict": verdict,
            "evidence": evidence,
            "summary": summary,
        }
        state["status"] = SUCCESS
        state["result"] = result
        self._save_state(record, state)
        return result

    def _environment_failure(self, record, state, reason, evidence):
        result = {
            "status": BLOCKED_ENVIRONMENT, "success": False, "run_id": record.run_id,
            "reason": reason, "evidence": evidence, "qa_verdict": state.get("last_qa_verdict"),
        }
        state["status"] = BLOCKED_ENVIRONMENT
        state["result"] = result
        self._save_state(record, state)
        return result

    def _blocked(self, record, state, plane_issue_id, status, reason, *, evidence=None):
        # Persist the deterministic/QA evidence before any external write.  A
        # Plane failure cannot erase the fact that the run was blocked.
        result = {
            "status": status,
            "success": False,
            "run_id": record.run_id,
            "reason": reason,
            "evidence": evidence,
            "qa_verdict": state.get("last_qa_verdict"),
        }
        state["status"] = status
        state["result"] = result
        self._save_state(record, state)
        if plane_issue_id and not state.get("plane_blocked"):
            try:
                state["plane_blocked"] = self.plane_update(
                    plane_issue_id, state="Blocked", summary=_blocked_summary(record, status, reason, evidence),
                )
                self._save_state(record, state)
            except Exception as exc:
                result["status"] = BLOCKED_ENVIRONMENT
                result["reason"] = f"{reason}; Plane Blocked update failed: {exc}"
                state["status"] = BLOCKED_ENVIRONMENT
                state["result"] = result
                self._save_state(record, state)
        return result

    @staticmethod
    def _state_path(record: RunRecord) -> Path:
        return Path(record.artifact_dir) / PIPELINE_STATE_FILENAME

    def _load_state(self, record: RunRecord) -> dict[str, Any]:
        path = self._state_path(record)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"schema_version": "1.0", "run_id": record.run_id, "status": "RUNNING", "fix_attempt": 0, "qa_attempt": 0, "execute_count": 0}

    def _save_state(self, record: RunRecord, state: dict[str, Any]) -> None:
        state["updated_at"] = _timestamp()
        path = self._state_path(record)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _save_qa_verdict(record: RunRecord, attempt: int, verdict: dict[str, Any]) -> None:
        path = Path(record.artifact_dir) / f"qa-verdict-{attempt:02d}.json"
        if not path.exists():
            path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalise_qa_output(output: Any) -> tuple[dict[str, Any] | None, str | None]:
    verdict = output.get("verdict") if isinstance(output, dict) and "decision" in output else output
    valid, errors = validate_verdict(verdict)
    if not valid:
        return None, "malformed QA verdict: " + "; ".join(errors)
    return verdict, None


def _qa_evidence_error(verdict: dict[str, Any], ticket_spec: dict[str, Any], run: RunRecord, qa_attempt: int) -> str | None:
    if verdict["issue_key"] != ticket_spec["issue_key"]:
        return "QA verdict issue_key does not match ticket-spec"
    if verdict["run_id"] != run.run_id:
        return "QA verdict run_id does not match Run"
    if verdict["qa_attempt"] != qa_attempt:
        return "QA verdict attempt does not match pipeline attempt"
    if verdict["verdict"] == "PASS":
        expected = {item["id"] for item in ticket_spec["acceptance_criteria"]}
        supplied = {item["id"] for item in verdict["acceptance_criteria"]}
        if supplied != expected:
            return "QA PASS omits ticket acceptance-criterion evidence"
        if any(item["status"] != "PASS" or not item["evidence"] for item in verdict["acceptance_criteria"]):
            return "QA PASS has missing or non-PASS acceptance evidence"
    if verdict["verdict"] == "FAIL":
        # A retry without evidenced original findings would invite the Executor
        # to guess.  That is an evidence failure, not a repair attempt.
        if not verdict["findings"] or any(not finding["evidence"] for finding in verdict["findings"]):
            return "QA FAIL has no evidenced original findings for a narrow fix"
    return None


def _verified_evidence(evidence: Any) -> bool:
    return isinstance(evidence, dict) and evidence.get("status") == VERIFIED and evidence.get("verified") is True and evidence.get("eligible_for_pr") is True and bool(evidence.get("checks"))


def _base_to_head_diff(run: RunRecord, evidence: dict[str, Any]) -> str:
    git = evidence.get("git", {})
    base, head = git.get("base_sha"), git.get("head_sha")
    if not base or not head:
        raise PipelineError("verification evidence lacks base/head SHA")
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", f"{base}..{head}"], cwd=run.worktree,
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise PipelineError(result.stderr.strip() or "git diff failed")
    return result.stdout


def _update_plane(issue_id: str, *, state: str, summary: str) -> dict[str, Any]:
    return plane.set_ticket_state(issue_id, state, summary)


def _summary(record: RunRecord, evidence: dict[str, Any], verdict: dict[str, Any], pr: dict[str, Any] | None) -> str:
    checks = ", ".join(f"{item.get('source')}={item.get('exit_code')}" for item in evidence.get("checks", []))
    pr_text = (pr or {}).get("url", "pending")
    return f"## Ticket Autopilot Run\n\nRun: `{record.run_id}`\nPR: {pr_text}\nChecks: {checks}\nQA: {verdict['verdict']} (attempt {verdict['qa_attempt']})\n"


def _blocked_summary(record: RunRecord, status: str, reason: str, evidence: dict[str, Any] | None) -> str:
    checks = ", ".join(f"{item.get('source')}={item.get('exit_code')}" for item in (evidence or {}).get("checks", []))
    return f"## Ticket Autopilot Blocked\n\nRun: `{record.run_id}`\nStatus: `{status}`\nReason: {reason}\nChecks: {checks or 'not run'}\n"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

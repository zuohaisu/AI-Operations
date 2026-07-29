"""Product-level controller glue for one owned Ticket Autopilot Run.

The controller deliberately composes the existing AIO-11 RunManager and AIO-13
TicketPipeline.  It adds only CLI concerns that those services do not own:
configuration preflight, selecting an owned Run, and a conservative local
lifecycle ledger for status/cancel/cleanup.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
from typing import Any, Callable

from ticket_autopilot.connectors import plane, qa
from ticket_autopilot.engine import drivers
from ticket_autopilot.services.development_verifier import DevelopmentVerifier
from ticket_autopilot.services.run_manager import RunManager, RunManagerError, RunRecord
from ticket_autopilot.services.ticket_contract import preflight_plane_issue
from ticket_autopilot.services.ticket_pipeline import TicketPipeline

LIFECYCLE_FILENAME = "controller-lifecycle-v1.json"
PIPELINE_FILENAME = "ticket-pipeline-state-v1.json"
_ISSUE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*$")

SUCCESS_STATUSES = frozenset({"IN_REVIEW", "CLEANED"})
NON_SUCCESS_STATUSES = frozenset({"ACTIVE", "CANCELLED", "STALLED"})


class ControllerError(RuntimeError):
    """A safe controller operation could not be completed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TicketController:
    """Thin CLI-facing adapter over the existing workflow services.

    Secrets are never accepted as configuration values: connectors resolve their
    credentials directly from environment variables.  The local repository and
    executable names are intentionally non-secret configuration.
    """

    def __init__(
        self,
        repository: str | Path | None = None,
        *,
        environ: dict[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        pipeline_factory: Callable[..., TicketPipeline] = TicketPipeline,
        terminate_group: Callable[[int], None] | None = None,
    ):
        self.environ = os.environ if environ is None else environ
        configured_repository = repository or self.environ.get("TICKET_AUTOPILOT_REPOSITORY")
        if not configured_repository:
            raise ControllerError(
                "REPOSITORY_REQUIRED",
                "set TICKET_AUTOPILOT_REPOSITORY to the local Git repository (or pass --repository)",
            )
        try:
            self.run_manager = RunManager(configured_repository)
        except Exception as exc:
            raise ControllerError("REPOSITORY_INVALID", f"local repository is not usable: {exc}") from exc
        self.which = which
        self.pipeline_factory = pipeline_factory
        self.terminate_group = terminate_group or self._terminate_group

    def run(self, issue_key: str) -> dict[str, Any]:
        self._validate_issue_key(issue_key)
        self._require_plane_credential()
        try:
            issue = plane.fetch_issue_by_identifier(issue_key)
        except Exception as exc:
            raise ControllerError("PLANE_READ_FAILED", f"could not read Plane issue {issue_key}: {exc}") from exc

        preflight = preflight_plane_issue(issue)
        if preflight["status"] != "READY":
            return self._preflight_result(issue_key, preflight)
        ticket_spec = preflight["ticket_spec"]
        if ticket_spec["issue_key"].casefold() != issue_key.casefold():
            raise ControllerError("ISSUE_KEY_MISMATCH", "Plane issue identifier does not match the requested issue key")

        # These checks are deliberately after the read-only contract gate but
        # before create_run, Agent spawn, PR creation, or Plane state writes.
        self._require_publish_credential()
        self._require_agent_clis()
        active = self._active_run_for_issue(issue_key)
        if active:
            return self._result_from_record(active, status="ACTIVE", reason="an owned Run is already active")

        try:
            record = self.run_manager.create_run(ticket_spec)
        except Exception as exc:
            raise ControllerError("RUN_CREATE_FAILED", str(exc)) from exc
        record = self.run_manager.update_state(record, "ACTIVE")
        self._write_lifecycle(record, "ACTIVE", controller_pid=os.getpid(), process_group=os.getpgrp())

        try:
            pipeline = self._build_pipeline()
            result = pipeline.run_existing(record, ticket_spec=ticket_spec, plane_issue_id=str(issue["id"]))
        except KeyboardInterrupt:
            result = self._result_from_record(record, status="CANCELLED", reason="controller interrupted")
        except Exception as exc:
            result = self._result_from_record(record, status="STALLED", reason=f"controller failed: {exc}")
        lifecycle_status = "COMPLETED" if result.get("status") in SUCCESS_STATUSES else result.get("status", "STALLED")
        record = self.run_manager.update_state(record, lifecycle_status)
        self._write_lifecycle(record, lifecycle_status, result=result)
        return result

    def status(self, issue_key: str, *, run_id: str | None = None) -> dict[str, Any]:
        self._validate_issue_key(issue_key)
        record = self._select_run(issue_key, run_id)
        lifecycle = self._read_lifecycle(record)
        pipeline = self._read_json(Path(record.artifact_dir) / PIPELINE_FILENAME) or {}
        result = pipeline.get("result") or lifecycle.get("result") or {}
        status = str(lifecycle.get("status") or pipeline.get("status") or record.state or "STALLED")
        if status == "COMPLETED":
            status = str(result.get("status") or "STALLED")
        pr = result.get("pr") or pipeline.get("pr")
        return {
            "run_id": record.run_id,
            "issue_key": record.issue_key,
            "status": status,
            "node": self._node_for(status, pipeline),
            "worktree": record.worktree,
            "branch": record.branch,
            "pr": (pr or {}).get("url") if isinstance(pr, dict) else pr,
            "attempt": record.attempt,
            "qa_attempt": pipeline.get("qa_attempt", record.qa_attempt),
            "updated_at": lifecycle.get("updated_at") or pipeline.get("updated_at") or record.updated_at,
            "blocked_reason": result.get("reason") if status.startswith("BLOCKED") else None,
        }

    def cancel(self, issue_key: str, *, run_id: str | None = None) -> dict[str, Any]:
        self._validate_issue_key(issue_key)
        record = self._select_run(issue_key, run_id)
        lifecycle = self._read_lifecycle(record)
        if lifecycle.get("status") != "ACTIVE":
            return self._result_from_record(record, status="BLOCKED", reason="Run is not active and cannot be cancelled")
        pid, group = lifecycle.get("controller_pid"), lifecycle.get("process_group")
        if not isinstance(pid, int) or not isinstance(group, int) or not self._owns_live_process(pid, group):
            return self._result_from_record(record, status="BLOCKED", reason="active Run has no verified controller process")
        try:
            self.terminate_group(group)
        except OSError as exc:
            return self._result_from_record(record, status="BLOCKED", reason=f"could not terminate owned Run: {exc}")
        result = self._result_from_record(record, status="CANCELLED", reason="owned controller process group terminated")
        record = self.run_manager.update_state(record, "CANCELLED")
        self._write_lifecycle(record, "CANCELLED", result=result)
        return result

    def cleanup(self, issue_key: str, *, run_id: str | None = None) -> dict[str, Any]:
        self._validate_issue_key(issue_key)
        record = self._select_run(issue_key, run_id)
        if self._read_lifecycle(record).get("status") == "ACTIVE":
            return self._result_from_record(record, status="BLOCKED", reason="refusing to clean an active Run")
        return self.run_manager.cleanup(record.run_id)

    def _build_pipeline(self) -> TicketPipeline:
        planner_cli = self.environ.get("TICKET_AUTOPILOT_PLANNER_CLI", "codex")
        developer_cli = self.environ.get("TICKET_AUTOPILOT_DEVELOPER_CLI", "claude")
        qa_cli = self.environ.get("TICKET_AUTOPILOT_QA_CLI", "qodercli")

        def planner(*, ticket_spec: dict[str, Any], run: RunRecord) -> object:
            agent = {
                "role": "planner", "command": planner_cli, "cwd": run.worktree,
                "permission_mode": "read-only", "tools": ["Read", "Glob", "Grep"],
                "allowed_roots": [run.worktree],
                "system": "Create a concise plan from this ticket contract. Do not modify files.",
            }
            return drivers.cli_call(agent, {"ticket_spec": ticket_spec}, {"agent": "planner"}, str(self.run_manager.repository))

        def executor(*, ticket_spec: dict[str, Any], plan: object, run: RunRecord, findings: object) -> object:
            agent = {
                "role": "developer", "command": developer_cli, "cwd": run.worktree,
                "branch": run.branch, "permission_mode": "write",
                "tools": ["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
                "allowed_roots": [run.worktree], "read_only": False,
                "tool_whitelist": ["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
                "system": "Implement only the ticket contract in this disposable worktree. Commit with the issue key.",
            }
            return drivers.cli_call(
                agent, {"ticket_spec": ticket_spec, "plan": plan, "findings": findings},
                {"agent": "developer"}, str(self.run_manager.repository),
                policy=self.run_manager.developer_policy(run), run_context=run.execution_context(),
            )

        def independent_qa(**kwargs: Any) -> dict[str, Any]:
            run = self.run_manager.load_run(kwargs["run_id"])
            agent = dict(qa.QA_AGENT, command=qa_cli, cwd=run.worktree, allowed_roots=[run.worktree])
            execution = kwargs.pop("execution", None)
            return qa.run_qa(agent=agent, engine_root=str(self.run_manager.repository), result=execution, **kwargs)

        return self.pipeline_factory(
            self.run_manager, planner=planner, executor=executor,
            verifier=DevelopmentVerifier(self.run_manager), qa=independent_qa,
        )

    def _require_plane_credential(self) -> None:
        # Explicitly require the environment: config-file credentials are not an
        # accepted product-CLI source.
        if not self.environ.get("PLANE_API_KEY"):
            raise ControllerError("CREDENTIAL_REQUIRED", "set PLANE_API_KEY in the environment")

    def _require_publish_credential(self) -> None:
        if not (self.environ.get("GITHUB_TOKEN") or self.environ.get("GH_TOKEN")):
            raise ControllerError("CREDENTIAL_REQUIRED", "set GITHUB_TOKEN or GH_TOKEN in the environment")

    def _require_agent_clis(self) -> None:
        missing = [
            name for name in (
                self.environ.get("TICKET_AUTOPILOT_PLANNER_CLI", "codex"),
                self.environ.get("TICKET_AUTOPILOT_DEVELOPER_CLI", "claude"),
                self.environ.get("TICKET_AUTOPILOT_QA_CLI", "qodercli"),
            ) if not self.which(name)
        ]
        if missing:
            raise ControllerError("AGENT_CLI_REQUIRED", "install or configure Agent CLI(s): " + ", ".join(missing))

    def _select_run(self, issue_key: str, run_id: str | None) -> RunRecord:
        records = self._records_for_issue(issue_key)
        if run_id:
            try:
                record = self.run_manager.load_run(run_id)
            except RunManagerError as exc:
                raise ControllerError("RUN_NOT_FOUND", str(exc)) from exc
            if record.issue_key.casefold() != issue_key.casefold():
                raise ControllerError("RUN_OWNERSHIP_MISMATCH", "run_id does not belong to the requested issue key")
            return record
        if not records:
            raise ControllerError("RUN_NOT_FOUND", f"no owned Run exists for {issue_key}")
        active = [record for record in records if self._read_lifecycle(record).get("status") == "ACTIVE"]
        if len(active) == 1:
            return active[0]
        if len(active) > 1:
            raise ControllerError("RUN_AMBIGUOUS", "more than one active owned Run; specify --run-id")
        return max(records, key=lambda item: item.updated_at)

    def _records_for_issue(self, issue_key: str) -> list[RunRecord]:
        if not self.run_manager.run_root.is_dir():
            return []
        records: list[RunRecord] = []
        for path in self.run_manager.run_root.iterdir():
            if not path.is_dir():
                continue
            try:
                record = self.run_manager.load_run(path.name)
            except RunManagerError:
                continue
            if record.issue_key.casefold() == issue_key.casefold():
                records.append(record)
        return records

    def _active_run_for_issue(self, issue_key: str) -> RunRecord | None:
        active = [record for record in self._records_for_issue(issue_key) if self._read_lifecycle(record).get("status") == "ACTIVE"]
        if len(active) > 1:
            raise ControllerError("RUN_AMBIGUOUS", "more than one active owned Run; specify --run-id")
        return active[0] if active else None

    @staticmethod
    def _validate_issue_key(issue_key: str) -> None:
        if not _ISSUE_KEY_RE.fullmatch(issue_key):
            raise ControllerError("ISSUE_KEY_INVALID", "issue key must be a value such as AIO-14")

    @staticmethod
    def _node_for(status: str, pipeline: dict[str, Any]) -> str:
        if status == "ACTIVE":
            return "pipeline"
        if status == "CANCELLED":
            return "cancel"
        if status == "CLEANED":
            return "cleanup"
        if status == "IN_REVIEW":
            return "publish"
        if status.startswith("BLOCKED"):
            return "blocked"
        return str(pipeline.get("node") or "unknown")

    def _write_lifecycle(self, record: RunRecord, status: str, **extra: Any) -> None:
        payload = {"schema_version": "1.0", "run_id": record.run_id, "issue_key": record.issue_key,
                   "status": status, "updated_at": _timestamp(), **extra}
        target = Path(record.artifact_dir) / LIFECYCLE_FILENAME
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _read_lifecycle(self, record: RunRecord) -> dict[str, Any]:
        return self._read_json(Path(record.artifact_dir) / LIFECYCLE_FILENAME) or {}

    @staticmethod
    def _owns_live_process(pid: int, process_group: int) -> bool:
        try:
            os.kill(pid, 0)
            return os.getpgid(pid) == process_group
        except OSError:
            return False

    @staticmethod
    def _terminate_group(process_group: int) -> None:
        os.killpg(process_group, signal.SIGTERM)

    @staticmethod
    def _result_from_record(record: RunRecord, *, status: str, reason: str) -> dict[str, Any]:
        return {"run_id": record.run_id, "issue_key": record.issue_key, "status": status, "success": False, "reason": reason}

    @staticmethod
    def _preflight_result(issue_key: str, preflight: dict[str, Any]) -> dict[str, Any]:
        errors = preflight.get("errors") or []
        reason = "; ".join(str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in errors)
        return {"run_id": None, "issue_key": issue_key, "status": preflight["status"], "success": False, "reason": reason}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

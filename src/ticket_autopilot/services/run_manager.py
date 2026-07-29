"""Disposable Run lifecycle: owned artifacts, one worktree, and one local branch.

This is intentionally not a controller or resume mechanism.  It records enough
immutable ownership information to make a later cleanup decision safe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any

from ticket_autopilot.engine.guardrails import (
    DEVELOPER_TOOL_WHITELIST,
    GuardrailPolicy,
    RunExecutionContext,
)
from ticket_autopilot.services.git_worktree import (
    GitWorktreeError,
    GitWorktreeService,
    is_protected_branch,
)
from ticket_autopilot.services.ticket_contract import validate_ticket_spec


_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,127}$")
_BRANCH_PREFIX = "agent/"


class RunManagerError(RuntimeError):
    """A Run cannot be created or a safe cleanup decision cannot be made."""


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    issue_key: str
    state: str
    repository: str
    artifact_dir: str
    worktree: str
    branch: str
    base_branch: str
    base_sha: str
    attempt: int
    qa_attempt: int
    fix_attempt: int
    created_at: str
    updated_at: str
    disposable: bool = True
    managed_by: str = "ticket-autopilot"

    @property
    def state_path(self) -> Path:
        return Path(self.artifact_dir) / "state.json"

    def execution_context(self) -> RunExecutionContext:
        return RunExecutionContext(
            run_id=self.run_id,
            worktree=self.worktree,
            branch=self.branch,
        )


class RunManager:
    """Own local Run paths beneath one repository's ``.ticket-autopilot`` root."""

    def __init__(
        self,
        repository: str | Path,
        *,
        run_root: str | Path | None = None,
        worktree_root: str | Path | None = None,
        git: GitWorktreeService | None = None,
    ):
        self.git = git or GitWorktreeService(repository)
        self.repository = self.git.repository
        runtime_root = self.repository / ".ticket-autopilot"
        self.run_root = self._absolute_under_repository(run_root or runtime_root / "runs")
        self.worktree_root = self._absolute_under_repository(
            worktree_root or runtime_root / "worktrees"
        )

    def create_run(self, ticket_spec: dict[str, Any], *, run_id: str | None = None) -> RunRecord:
        """Create one unique feature branch/worktree from a schema-valid R0/R1 spec."""
        self._validate_ticket_spec(ticket_spec)
        issue_key = str(ticket_spec["issue_key"])
        run_id = run_id or self._new_run_id(issue_key)
        self._validate_run_id(run_id)

        artifact_dir = self._child(self.run_root, run_id)
        worktree = self._child(self.worktree_root, run_id)
        if artifact_dir.exists() or worktree.exists():
            raise RunManagerError(f"run id already owns a target path: {run_id}")

        base_sha = self.git.head_sha()
        base_branch = self.git.current_branch()
        branch = self._branch_name(issue_key, run_id)
        if is_protected_branch(branch):  # defensive: generated branches must never be protected.
            raise RunManagerError(f"generated protected branch name: {branch}")

        now = _timestamp()
        record = RunRecord(
            run_id=run_id,
            issue_key=issue_key,
            state="CREATED",
            repository=str(self.repository),
            artifact_dir=str(artifact_dir),
            worktree=str(worktree),
            branch=branch,
            base_branch=base_branch,
            base_sha=base_sha,
            attempt=0,
            qa_attempt=0,
            fix_attempt=0,
            created_at=now,
            updated_at=now,
        )

        artifact_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._write_json(artifact_dir / "ticket-spec.json", ticket_spec)
            # A retained controller log exists from creation, even if a later action fails.
            (artifact_dir / "controller.log").touch(exist_ok=False)
            self.git.create_worktree(worktree, branch, base_sha)
            self._write_state(record)
        except Exception:
            # Do not guess how to clean a partially-created Git worktree.  Keep the
            # owned artifact directory for forensic inspection and surface the failure.
            raise
        return record

    # Convenient aliases for callers/tests that describe the operation differently.
    create = create_run

    def load_run(self, run_id: str) -> RunRecord:
        self._validate_run_id(run_id)
        state_path = self._child(self.run_root, run_id) / "state.json"
        if not state_path.is_file():
            raise RunManagerError(f"unknown run: {run_id}")
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            record = RunRecord(**raw)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RunManagerError(f"run state is unreadable: {run_id}") from exc
        self._assert_owned_record(record, run_id)
        return record

    get_run = load_run

    def update_state(self, run: RunRecord | str, state: str) -> RunRecord:
        """Persist a lifecycle state only after reloading the owned Run record."""
        if not isinstance(state, str) or not state:
            raise RunManagerError("Run state must be a non-empty string")
        record = self.load_run(run if isinstance(run, str) else run.run_id)
        updated = RunRecord(**{**asdict(record), "state": state, "updated_at": _timestamp()})
        self._write_state(updated)
        return updated

    def developer_policy(self, run: RunRecord | str) -> GuardrailPolicy:
        """The only policy that permits mutation: the exact disposable worktree."""
        record = self.load_run(run if isinstance(run, str) else run.run_id)
        self._assert_owned_record(record, record.run_id)
        return GuardrailPolicy(
            allowed_roots=[record.worktree],
            read_only=False,
            tool_whitelist=list(DEVELOPER_TOOL_WHITELIST),
        )

    def cleanup(self, run: RunRecord | str) -> dict[str, Any]:
        """Remove only an owned *unmerged* local Run; always retain artifacts."""
        try:
            # Reload canonical state even when passed a RunRecord: accepting a
            # caller-constructed record would not prove ownership of the target.
            record = self.load_run(run if isinstance(run, str) else run.run_id)
            self._assert_owned_record(record, record.run_id)
            self._assert_cleanup_target(record)
        except (RunManagerError, GitWorktreeError, OSError, TypeError, ValueError, AttributeError) as exc:
            return {"status": "BLOCKED", "reason": str(exc), "run_id": getattr(run, "run_id", run)}

        merged = self.git.is_branch_merged(record.branch, record.base_branch)
        if merged is None:
            return self._blocked(record, "cannot determine whether the branch is merged")
        if merged:
            return self._blocked(record, "refusing to clean a merged branch")

        try:
            self.git.remove_worktree(record.worktree)
            self.git.delete_unmerged_branch(record.branch)
        except GitWorktreeError as exc:
            return self._blocked(record, str(exc))

        cleaned = RunRecord(**{**asdict(record), "state": "CLEANED", "updated_at": _timestamp()})
        self._write_state(cleaned)
        return {
            "status": "CLEANED",
            "run_id": cleaned.run_id,
            "worktree_removed": True,
            "branch_removed": True,
            "artifact_dir": cleaned.artifact_dir,
        }

    cleanup_run = cleanup

    @staticmethod
    def _blocked(record: RunRecord, reason: str) -> dict[str, Any]:
        return {"status": "BLOCKED", "run_id": record.run_id, "reason": reason}

    def _validate_ticket_spec(self, ticket_spec: dict[str, Any]) -> None:
        valid, errors = validate_ticket_spec(ticket_spec)
        if not valid:
            raise RunManagerError("ticket-spec is not valid: " + "; ".join(errors))
        if ticket_spec["risk_tier"] not in {"R0", "R1"}:
            raise RunManagerError("ticket-spec risk tier is not automatable")
        if ticket_spec["constraints"].get("allow_main_push") is not False:
            raise RunManagerError("ticket-spec must explicitly forbid main branch push")

    def _assert_cleanup_target(self, record: RunRecord) -> None:
        worktree = Path(record.worktree)
        expected_worktree = self._child(self.worktree_root, record.run_id)
        if worktree != expected_worktree:
            raise RunManagerError("worktree target is not the run's canonical disposable path")
        if not worktree.is_dir():
            raise RunManagerError("worktree target is missing or ambiguous")
        if not record.branch.startswith(_BRANCH_PREFIX) or is_protected_branch(record.branch):
            raise RunManagerError("branch is not a disposable feature branch")
        if not self.git.branch_exists(record.branch):
            raise RunManagerError("local feature branch is missing or ambiguous")
        actual_branch = self.git.worktree_branch(worktree)
        if actual_branch != record.branch:
            raise RunManagerError("worktree branch does not match owned run state")
        if is_protected_branch(actual_branch):
            raise RunManagerError("refusing to clean a protected worktree branch")

    def _assert_owned_record(self, record: RunRecord, requested_run_id: str) -> None:
        if record.run_id != requested_run_id:
            raise RunManagerError("run state id does not match requested target")
        if not record.disposable or record.managed_by != "ticket-autopilot":
            raise RunManagerError("run state does not prove Ticket Autopilot ownership")
        if Path(record.repository).resolve() != self.repository:
            raise RunManagerError("run state belongs to another repository")
        if Path(record.artifact_dir).resolve() != self._child(self.run_root, record.run_id):
            raise RunManagerError("artifact target is not the run's canonical path")
        if Path(record.worktree).resolve() != self._child(self.worktree_root, record.run_id):
            raise RunManagerError("worktree target is not the run's canonical path")
        try:
            expected_branch = self._branch_name(record.issue_key, record.run_id)
        except (AttributeError, TypeError) as exc:
            raise RunManagerError("run state has no safe issue key or branch") from exc
        if record.branch != expected_branch:
            raise RunManagerError("branch is not the run's generated disposable branch")

    def _write_state(self, record: RunRecord) -> None:
        self._write_json(record.state_path, asdict(record))

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _absolute_under_repository(self, path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        try:
            target.relative_to(self.repository)
        except ValueError as exc:
            raise RunManagerError(f"runtime path must be inside repository: {target}") from exc
        return target

    @staticmethod
    def _child(root: Path, run_id: str) -> Path:
        target = (root / run_id).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise RunManagerError("run path escapes its configured root") from exc
        return target

    @staticmethod
    def _branch_name(issue_key: str, run_id: str) -> str:
        prefix = re.sub(r"[^a-z0-9-]+", "-", issue_key.casefold()).strip("-")
        if not prefix:
            raise RunManagerError("issue key cannot form a safe branch name")
        return f"{_BRANCH_PREFIX}{prefix}-{run_id}"

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise RunManagerError("run_id must be lowercase, path-safe, and at least 3 characters")

    def _new_run_id(self, issue_key: str) -> str:
        prefix = re.sub(r"[^a-z0-9-]+", "-", issue_key.casefold()).strip("-")
        if not prefix:
            raise RunManagerError("issue key cannot form a safe run id")
        return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}-{secrets.token_hex(3)}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

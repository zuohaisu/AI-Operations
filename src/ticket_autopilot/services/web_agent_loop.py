"""Web-facing, append-only Developer/QA evidence loop for one owned Run."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import threading
from typing import Any, Callable

from ticket_autopilot.schemas.qa_verdict import validate_verdict
from ticket_autopilot.services.delivery_policy import require_user_authorization
from ticket_autopilot.services.process_output import ProcessOutputStore
from ticket_autopilot.services.run_events import redact
from ticket_autopilot.services.run_manager import RunManager, RunRecord

MAX_QA_ATTEMPTS = 5
ACTIVE = "ACTIVE"
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
HARD_BREAK = "HARD_BREAK"
QA_EXHAUSTED = "QA_EXHAUSTED"
STOPPED = "STOPPED"
_CANONICAL = frozenset({"QA_PENDING", "HUMAN_VISUAL_REVIEW_PENDING", "READY_FOR_REVIEW", "DIFF_SPLIT_REQUIRED", "USER_OVERRIDE_APPROVED", "MERGE_AUTHORIZED_BY_USER", "TECHNICAL_BLOCKED"})


class WebAgentLoopError(RuntimeError):
    """A Web Run cannot safely start or continue."""


class WebAgentLoop:
    """Start one asynchronous, isolated Developer -> checks -> QA Run.

    The state snapshot is recoverable; every user-visible fact is first appended
    to ``events.jsonl``.  No callback output is trusted as process ownership.
    A caller that launches a child process may register its verified process
    group through ``register_owned_process_group`` for safe Stop support.
    """

    _lock = threading.RLock()

    def __init__(
        self,
        run_manager: RunManager,
        *,
        developer: Callable[..., Any],
        checker: Callable[..., dict[str, Any]],
        qa: Callable[..., Any],
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        git_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        terminate_group: Callable[[int], None] | None = None,
        owns_process_group: Callable[[int, int], bool] | None = None,
        known_secrets: tuple[str, ...] = (),
    ):
        self.run_manager = run_manager
        self.developer, self.checker, self.qa = developer, checker, qa
        self.thread_factory, self.git_runner = thread_factory, git_runner
        self.terminate_group = terminate_group or self._terminate_group
        self.owns_process_group = owns_process_group or self._owns_process_group
        self.known_secrets = tuple(value for value in known_secrets if value)
        self._threads: dict[str, threading.Thread] = {}
        self._prompts: dict[str, tuple[str, str]] = {}
        self._process_groups: dict[str, tuple[int, int]] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def start(
        self,
        ticket_spec: dict[str, Any],
        *,
        developer_prompt: str,
        qa_prompt: str,
        prompt_sources: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create ownership synchronously, then return the Run id before work."""
        issue_key = str(ticket_spec.get("issue_key", ""))
        if not developer_prompt.strip() or not qa_prompt.strip():
            raise WebAgentLoopError("BLOCKED_REQUIREMENTS: Developer and QA Prompts are required")
        with self._lock:
            if self._active_for(issue_key):
                return {"status": BLOCKED, "reason": "an owned Run is already active", "run_id": None, "developer_calls": 0, "qa_calls": 0}
            record = self.run_manager.create_run(ticket_spec)
            record = self.run_manager.update_state(record, ACTIVE)
            self._prompts[record.run_id] = (developer_prompt, qa_prompt)
            self._stop_events[record.run_id] = threading.Event()
            state = self._initial_state(record, prompt_sources)
            self._save(record, state)
            self._event(record, stage="planner", role="planner", status="PROMPTS_READY", event_type="prompt_sources_recorded", artifact_refs=("state.json",), details={"prompt_sources": state["prompt_sources"]}, actor_type="agent")
            self._event(record, stage="delivery", role="controller", status="HUMAN_VISUAL_REVIEW_PENDING", event_type="visual_review_pending", artifact_refs=("state.json",), details={"reason": "browser visual evidence has not yet been recorded"})
            thread = self.thread_factory(target=self._run, args=(record.run_id,), daemon=True, name=f"ticket-autopilot-{record.run_id}")
            self._threads[record.run_id] = thread
            thread.start()
        return {"status": ACTIVE, "run_id": record.run_id, "issue_key": record.issue_key, "worktree": record.worktree, "branch": record.branch}

    def status(self, run_id: str) -> dict[str, Any]:
        record = self.run_manager.load_run(run_id)
        return self._load(record)

    def timeline(self, run_id: str) -> dict[str, Any]:
        record = self.run_manager.load_run(run_id)
        snapshot = self._load(record)
        return {
            "run_id": record.run_id,
            "snapshot": redact(snapshot, self.known_secrets),
            "events": self.run_manager.events(record),
            "process_output": ProcessOutputStore(
                record.artifact_dir, known_secrets=self.known_secrets,
            ).read(),
        }

    def register_owned_process_group(self, run_id: str, *, pid: int, process_group: int) -> None:
        """Register only a controller-created child after PID/group verification."""
        record = self.run_manager.load_run(run_id)
        if not isinstance(pid, int) or not isinstance(process_group, int) or pid <= 1 or process_group <= 1 or not self.owns_process_group(pid, process_group):
            raise WebAgentLoopError("BLOCKED_NEEDS_HUMAN: process identity is not a verified owned process group")
        self._process_groups[record.run_id] = (pid, process_group)
        self._event(record, stage="run", role="controller", status=ACTIVE, event_type="owned_process_registered", details={"pid": pid, "process_group": process_group})

    def stop(self, run_id: str) -> dict[str, Any]:
        """Terminate exactly a verified controller-owned process group, never a PID supplied by the UI."""
        record = self.run_manager.load_run(run_id)
        state = self._load(record)
        if state.get("status") not in {ACTIVE, "DEVELOPING", "VERIFYING", "QA_RUNNING"}:
            return {"run_id": run_id, "status": BLOCKED, "reason": "Run is not active"}
        identity = self._process_groups.get(run_id)
        if identity is None or not self.owns_process_group(*identity):
            self._event(record, stage="run", role="controller", status="BLOCKED_NEEDS_HUMAN", event_type="stop_rejected", details={"reason": "Run has no verified owned process group"})
            return {"run_id": run_id, "status": "BLOCKED_NEEDS_HUMAN", "reason": "Run has no verified owned process group"}
        try:
            self.terminate_group(identity[1])
        except OSError as exc:
            self._event(record, stage="run", role="controller", status="TECHNICAL_BLOCKED", event_type="stop_failed", details={"reason": str(exc)})
            return {"run_id": run_id, "status": "TECHNICAL_BLOCKED", "reason": "could not terminate owned Run process group"}
        self._stop_events.setdefault(run_id, threading.Event()).set()
        state.update({"state": STOPPED, "status": STOPPED, "stopped_process_group": identity[1]})
        self._save(record, state)
        self.run_manager.update_state(record, STOPPED)
        self._event(record, stage="run", role="controller", status=STOPPED, event_type="run_stopped", artifact_refs=("state.json",), details={"process_group": identity[1]})
        return {"run_id": run_id, "status": STOPPED, "artifact_dir": record.artifact_dir}

    def retry_current_stage(self, run_id: str) -> dict[str, Any]:
        """Retry a terminal stage on the same Run without rewriting its history."""
        with self._lock:
            record = self.run_manager.load_run(run_id)
            state = self._load(record)
            if state.get("status") not in {HARD_BREAK, BLOCKED, QA_EXHAUSTED}:
                return {"run_id": run_id, "status": BLOCKED, "reason": "current Run state is not eligible for retry"}
            if run_id not in self._prompts:
                return {"run_id": run_id, "status": "BLOCKED_NEEDS_HUMAN", "reason": "prompt execution context is unavailable after service restart"}
            stage = str((state.get("hard_break") or {}).get("stage") or state.get("state") or "run")
            state.update({"state": ACTIVE, "status": ACTIVE, "retry_from_stage": stage})
            self._save(record, state)
            self.run_manager.update_state(record, ACTIVE)
            self._event(record, stage=stage, role="controller", round=int(state.get("qa_attempt") or 0), status=ACTIVE, event_type="retry_requested", artifact_refs=("state.json",), details={"retry_from_stage": stage})
            self._stop_events[run_id] = threading.Event()
            thread = self.thread_factory(target=self._run, args=(run_id,), daemon=True, name=f"ticket-autopilot-{run_id}-retry")
            self._threads[run_id] = thread
            thread.start()
        return {"run_id": run_id, "status": ACTIVE, "retry_from_stage": stage}

    def record_owner_action(self, run_id: str, authorization: dict[str, Any]) -> dict[str, Any]:
        """Record a repository-owner decision only; this endpoint performs no remote mutation."""
        action = str(authorization.get("action") or "")
        audit = require_user_authorization(authorization, action=action)
        record = self.run_manager.load_run(run_id)
        state = self._load(record)
        status = {"override_gate": "USER_OVERRIDE_APPROVED", "merge": "MERGE_AUTHORIZED_BY_USER", "visual_accept": "READY_FOR_REVIEW"}.get(action, "READY_FOR_REVIEW")
        state.setdefault("owner_actions", []).append(audit)
        self._save(record, state)  # Preserve the original gate verdict/status.
        self._event(record, stage="delivery", role="repository_owner", status=status, event_type="owner_action_recorded", artifact_refs=("state.json",), details=audit, actor_type="repository_owner")
        return {"run_id": run_id, "status": status, "authorization": audit, "original_status": state.get("status")}

    def _run(self, run_id: str) -> None:
        record = self.run_manager.load_run(run_id)
        state = self._load(record)
        try:
            start = max(1, int(state.get("qa_attempt") or 0) or 1)
            for attempt in range(start, MAX_QA_ATTEMPTS + 1):
                if self._stopped(run_id):
                    return
                state["qa_attempt"] = attempt
                state["state"] = "DEVELOPING"
                self._save(record, state)
                self._event(record, stage="development", role="developer", round=attempt, status="RUNNING", event_type="agent_started", details={"worktree": record.worktree}, actor_type="developer_agent")
                developer_prompt, _ = self._prompts[run_id]
                try:
                    output = self.developer(ticket_spec=state["ticket_spec"], prompt=developer_prompt, run=asdict(record), findings=state.get("findings"), qa_attempt=attempt, role="developer", permission_mode="write")
                except Exception as exc:
                    self._hard_break(record, state, "development", "developer", attempt, "DEVELOPER_PROCESS_FAILED", exc)
                    return
                state["developer_processes"].append(self._identity(output, "developer", attempt))
                self._event(record, stage="development", role="developer", round=attempt, status="COMPLETED", event_type="agent_completed", details={"process": state["developer_processes"][-1]}, actor_type="developer_agent")

                state["state"] = "VERIFYING"
                self._save(record, state)
                self._event(record, stage="verification", role="controller", round=attempt, status="RUNNING", event_type="checks_started")
                try:
                    evidence = self.checker(record, qa_attempt=attempt)
                except Exception as exc:
                    self._hard_break(record, state, "verification", "controller", attempt, "CHECK_PROCESS_FAILED", exc)
                    return
                if not self._eligible_checks(evidence):
                    self._blocked(record, state, "deterministic checks did not produce eligible evidence", evidence, attempt)
                    return
                changed_files = evidence.get("changed_files") or evidence.get("git", {}).get("changed_files", [])
                self._event(record, stage="verification", role="controller", round=attempt, status="PASS", event_type="checks_completed", details={"checks": evidence.get("checks", []), "changed_files": changed_files, "provenance": evidence.get("provenance", {})})
                if not self._safe_paths(changed_files):
                    self._blocked(record, state, "DIFF_SPLIT_REQUIRED: changed files are unsafe or not ticket-owned", evidence, attempt)
                    return
                diff = evidence.get("diff")
                if not isinstance(diff, str) or not diff.strip():
                    self._blocked(record, state, "BLOCKED_NEEDS_HUMAN: base-to-current Diff is empty or unavailable", evidence, attempt)
                    return

                state["state"] = "QA_RUNNING"
                self._save(record, state)
                self._event(record, stage="qa", role="qa", round=attempt, status="RUNNING", event_type="agent_started", details={"changed_files": changed_files}, actor_type="qa_agent")
                _, qa_prompt = self._prompts[run_id]
                qa_input = {"ticket_spec": state["ticket_spec"], "prompt": qa_prompt, "run": asdict(record), "diff": diff, "changed_files": changed_files, "check_evidence": evidence.get("checks", []), "verification_evidence": evidence, "qa_attempt": attempt, "role": "qa", "permission_mode": "read-only"}
                try:
                    raw = self.qa(**qa_input)
                except Exception as exc:
                    self._hard_break(record, state, "qa", "qa", attempt, "QA_PROCESS_FAILED", exc)
                    return
                verdict = raw.get("verdict") if isinstance(raw, dict) and "decision" in raw else raw
                valid, errors = validate_verdict(verdict)
                if not valid:
                    self._hard_break(record, state, "qa", "qa", attempt, "QA_MALFORMED_OUTPUT", "; ".join(errors))
                    return
                assert isinstance(verdict, dict)
                verdict_error = self._verdict_error(verdict, state["ticket_spec"])
                if verdict_error or verdict.get("issue_key") != record.issue_key or verdict.get("run_id") != record.run_id or verdict.get("qa_attempt") != attempt:
                    self._hard_break(record, state, "qa", "qa", attempt, "QA_EVIDENCE_MISMATCH" if not verdict_error else "QA_MALFORMED_OUTPUT", verdict_error or "QA verdict identity does not match this attempt")
                    return
                state["qa_processes"].append(self._identity(raw, "qa", attempt))
                attempt_record = {"qa_attempt": attempt, "input_hash": self._hash(qa_input), "findings": verdict["findings"], "changed_files": changed_files, "checks": evidence.get("checks", []), "verification_provenance": evidence.get("provenance", {}), "verdict": verdict}
                state["attempts"].append(attempt_record)
                self._write_json(Path(record.artifact_dir) / f"qa-verdict-{attempt:02d}.json", verdict)
                self._event(record, stage="qa", role="qa", round=attempt, status=verdict["verdict"], event_type="qa_verdict_recorded", artifact_refs=(f"qa-verdict-{attempt:02d}.json",), details={"findings": verdict["findings"], "changed_files": changed_files, "checks": evidence.get("checks", [])}, actor_type="qa_agent")
                if verdict["verdict"] == "BLOCKED":
                    self._blocked(record, state, "QA returned BLOCKED", evidence, attempt)
                    return
                if verdict["verdict"] == "PASS":
                    commit = self._commit(record, state["ticket_spec"], changed_files)
                    if isinstance(commit, str):
                        self._blocked(record, state, commit, evidence, attempt)
                        return
                    state.update({"state": PASS, "status": PASS, "commit": commit, "findings": None})
                    self._save(record, state)
                    self.run_manager.update_state(record, PASS)
                    self._event(record, stage="commit", role="controller", round=attempt, status="COMPLETED", event_type="commit_recorded", artifact_refs=("state.json",), details=commit)
                    return
                self._event(record, stage="delivery", role="controller", round=attempt, status="QA_PENDING", event_type="delivery_gate_recorded", artifact_refs=(f"qa-verdict-{attempt:02d}.json",), details={"qa_verdict": "FAIL", "findings": verdict["findings"]})
                state["findings"] = verdict["findings"]
                if attempt == MAX_QA_ATTEMPTS:
                    state.update({"state": QA_EXHAUSTED, "status": QA_EXHAUSTED})
                    self._save(record, state)
                    self.run_manager.update_state(record, QA_EXHAUSTED)
                    self._event(record, stage="qa", role="qa", round=attempt, status=QA_EXHAUSTED, event_type="qa_attempts_exhausted", artifact_refs=("state.json",), details={"findings": verdict["findings"]}, actor_type="qa_agent")
                    return
                self._save(record, state)
        except Exception as exc:
            self._hard_break(record, state, "run", "controller", int(state.get("qa_attempt") or 0), "LOOP_ENVIRONMENT_FAILED", exc)

    def _commit(self, record: RunRecord, ticket_spec: dict[str, Any], changed_files: list[str]) -> dict[str, str] | str:
        if not changed_files or not self._safe_paths(changed_files): return "BLOCKED_NEEDS_HUMAN: no safe ticket-owned files to commit"
        worktree = Path(record.worktree)
        output = ProcessOutputStore(record.artifact_dir, known_secrets=self.known_secrets)
        try:
            output.append(stage="commit", role="controller", stream="process",
                          message=f"staging {len(changed_files)} ticket-owned path(s)", round=int(ticket_spec.get("qa_attempt") or 0))
            result = self.git_runner(["git", "add", "--", *changed_files], cwd=worktree, capture_output=True, text=True, check=False)
            if result.returncode: return f"TECHNICAL_BLOCKED: git add failed: {result.stderr.strip()}"
            staged = self.git_runner(["git", "diff", "--cached", "--name-only"], cwd=worktree, capture_output=True, text=True, check=False)
            staged_files = [line for line in staged.stdout.splitlines() if line]
            if staged.returncode or set(staged_files) != set(changed_files): return "DIFF_SPLIT_REQUIRED: staged files differ from ticket-owned changed files"
            commit = self.git_runner(["git", "commit", "-m", f"{record.issue_key}: verified Web Run"], cwd=worktree, capture_output=True, text=True, check=False)
            if commit.returncode: return f"TECHNICAL_BLOCKED: git commit failed: {commit.stderr.strip()}"
            output.append(stage="commit", role="controller", stream="stdout",
                          message=commit.stdout or "git commit completed", round=0)
            sha = self.git_runner(["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False)
            return "TECHNICAL_BLOCKED: cannot record Commit SHA" if sha.returncode else {"branch": record.branch, "sha": sha.stdout.strip(), "changed_files": staged_files}
        except (OSError, subprocess.SubprocessError) as exc: return f"TECHNICAL_BLOCKED: git commit operation failed: {exc}"

    def _active_for(self, issue_key: str) -> bool:
        for path in self.run_manager.run_root.glob("*/state.json"):
            try: record = self.run_manager.load_run(path.parent.name)
            except Exception: continue
            if record.issue_key.casefold() == issue_key.casefold() and record.state == ACTIVE: return True
        return False

    @staticmethod
    def _verdict_error(verdict: dict[str, Any], ticket_spec: dict[str, Any]) -> str | None:
        if verdict["verdict"] == "FAIL" and not verdict["findings"]: return "QA FAIL has no original findings to provide to Developer"
        if verdict["verdict"] == "PASS":
            expected, supplied = {item["id"] for item in ticket_spec["acceptance_criteria"]}, {item["id"] for item in verdict["acceptance_criteria"]}
            if supplied != expected or any(item["status"] != "PASS" or not item["evidence"] for item in verdict["acceptance_criteria"]): return "QA PASS lacks complete passing acceptance evidence"
        return None

    @staticmethod
    def _eligible_checks(evidence: Any) -> bool:
        return isinstance(evidence, dict) and evidence.get("verified") is True and bool(evidence.get("checks")) and all(item.get("exit_code") == 0 for item in evidence["checks"])

    @staticmethod
    def _safe_paths(paths: Any) -> bool:
        return isinstance(paths, list) and bool(paths) and all(isinstance(path, str) and path and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and not path.startswith(".git/") for path in paths)

    def _initial_state(self, record: RunRecord, prompt_sources: dict[str, Any] | None) -> dict[str, Any]:
        return {"schema_version": "1.0", "run_id": record.run_id, "issue_key": record.issue_key, "state": ACTIVE, "status": ACTIVE, "ticket_spec": json.loads((Path(record.artifact_dir) / "ticket-spec.json").read_text()), "prompt_sources": prompt_sources or {"developer": {"source": "provided_at_run_start"}, "qa": {"source": "provided_at_run_start"}}, "worktree": record.worktree, "qa_attempt": 0, "findings": None, "attempts": [], "developer_processes": [], "qa_processes": [], "owner_actions": [], "pre_existing_dirty_paths": self._dirty_paths(Path(record.repository))}

    def _hard_break(self, record: RunRecord, state: dict[str, Any], stage: str, role: str, round: int, code: str, error: object) -> None:
        details = {"code": code, "reason": str(error), "stage": stage, "role": role, "round": round, "worktree": record.worktree, "allowed_human_actions": ["retry_current_stage", "stop", "inspect_worktree"]}
        state.update({"state": HARD_BREAK, "status": HARD_BREAK, "hard_break": details})
        self._save(record, state); self.run_manager.update_state(record, HARD_BREAK)
        self._event(record, stage=stage, role=role, round=round, status=HARD_BREAK, event_type="hard_break", artifact_refs=("state.json",), details=details, actor_type="qa_agent" if role == "qa" else "developer_agent" if role == "developer" else "system")

    def _blocked(self, record: RunRecord, state: dict[str, Any], reason: str, evidence: dict[str, Any], round: int) -> None:
        canonical = reason.split(":", 1)[0] if reason.split(":", 1)[0] in _CANONICAL else BLOCKED
        state.update({"state": BLOCKED, "status": BLOCKED, "reason": reason, "last_check_evidence": evidence})
        self._save(record, state); self.run_manager.update_state(record, BLOCKED)
        self._event(record, stage="verification", role="controller", round=round, status=canonical, event_type="run_blocked", artifact_refs=("state.json",), details={"reason": reason, "changed_files": evidence.get("changed_files", [])})

    @staticmethod
    def _identity(output: Any, role: str, attempt: int) -> dict[str, Any]:
        identity = output.get("process_identity") if isinstance(output, dict) else None
        return {"role": role, "qa_attempt": attempt, "identity": identity or f"{role}-attempt-{attempt}"}

    @staticmethod
    def _hash(value: Any) -> str: return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def _dirty_paths(self, repository: Path) -> list[str]:
        result = self.git_runner(["git", "status", "--porcelain"], cwd=repository, capture_output=True, text=True, check=False)
        return [line[3:] for line in result.stdout.splitlines() if len(line) > 3]

    @staticmethod
    def _state_path(record: RunRecord) -> Path: return Path(record.artifact_dir) / "web-agent-loop-state-v1.json"
    def _load(self, record: RunRecord) -> dict[str, Any]: return json.loads(self._state_path(record).read_text(encoding="utf-8"))
    def _save(self, record: RunRecord, state: dict[str, Any]) -> None: self._write_json(self._state_path(record), state)
    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp"); temporary.write_text(json.dumps(redact(payload, self.known_secrets), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"); temporary.replace(path)
    def _event(self, record: RunRecord, **kwargs: Any) -> None:
        kwargs["details"] = redact(kwargs.get("details") or {}, self.known_secrets)
        self.run_manager.append_event(record, **kwargs)
    def _stopped(self, run_id: str) -> bool: return self._stop_events.get(run_id, threading.Event()).is_set()
    @staticmethod
    def _terminate_group(process_group: int) -> None: os.killpg(process_group, signal.SIGTERM)
    @staticmethod
    def _owns_process_group(pid: int, process_group: int) -> bool:
        try: os.kill(pid, 0); return os.getpgid(pid) == process_group
        except OSError: return False

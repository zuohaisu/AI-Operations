"""Web-facing bounded Developer/QA loop for one owned Run.

This is an adapter, not another controller: RunManager remains the authority for
worktree ownership and this module performs no Plane, push, PR, merge, or deploy
operation.  It deliberately commits only after independent QA has passed.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import threading
from typing import Any, Callable

from ticket_autopilot.schemas.qa_verdict import validate_verdict
from ticket_autopilot.services.run_manager import RunManager, RunRecord

MAX_QA_ATTEMPTS = 5
ACTIVE = "ACTIVE"
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
HARD_BREAK = "HARD_BREAK"
QA_EXHAUSTED = "QA_EXHAUSTED"


class WebAgentLoopError(RuntimeError):
    """A Web Run cannot safely start or continue."""


class WebAgentLoop:
    """Start one asynchronous, isolated Developer -> checks -> QA Run.

    Collaborators are injected so this boundary is fully testable without an
    Agent, Plane, GitHub, or network.  ``checker`` receives an owned Run and
    returns deterministic evidence including ``changed_files`` and ``checks``.
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
    ):
        self.run_manager = run_manager
        self.developer = developer
        self.checker = checker
        self.qa = qa
        self.thread_factory = thread_factory
        self.git_runner = git_runner
        self._threads: dict[str, threading.Thread] = {}

    def start(self, ticket_spec: dict[str, Any], *, developer_prompt: str, qa_prompt: str) -> dict[str, Any]:
        """Create ownership synchronously, then return the Run id without waiting."""
        issue_key = str(ticket_spec.get("issue_key", ""))
        if not developer_prompt.strip() or not qa_prompt.strip():
            raise WebAgentLoopError("BLOCKED_REQUIREMENTS: Developer and QA Prompts are required")
        with self._lock:
            if self._active_for(issue_key):
                return {"status": BLOCKED, "reason": "an owned Run is already active", "run_id": None,
                        "developer_calls": 0, "qa_calls": 0}
            record = self.run_manager.create_run(ticket_spec)
            record = self.run_manager.update_state(record, ACTIVE)
            state = self._initial_state(record, developer_prompt, qa_prompt)
            self._save(record, state)
            thread = self.thread_factory(target=self._run, args=(record.run_id,), daemon=True,
                                         name=f"ticket-autopilot-{record.run_id}")
            self._threads[record.run_id] = thread
            thread.start()
        return {"status": ACTIVE, "run_id": record.run_id, "issue_key": record.issue_key,
                "worktree": record.worktree, "branch": record.branch}

    def status(self, run_id: str) -> dict[str, Any]:
        record = self.run_manager.load_run(run_id)
        return self._load(record)

    def _run(self, run_id: str) -> None:
        record = self.run_manager.load_run(run_id)
        state = self._load(record)
        try:
            for attempt in range(1, MAX_QA_ATTEMPTS + 1):
                state["qa_attempt"] = attempt
                state["state"] = "DEVELOPING"
                self._save(record, state)
                developer_input = {
                    "ticket_spec": state["ticket_spec"], "prompt": state["developer_prompt"],
                    "run": asdict(record), "findings": state.get("findings"),
                    "role": "developer", "permission_mode": "write",
                }
                try:
                    output = self.developer(**developer_input)
                except Exception as exc:
                    self._hard_break(record, state, "DEVELOPER_PROCESS_FAILED", exc)
                    return
                state["developer_processes"].append(self._identity(output, "developer", attempt))

                state["state"] = "VERIFYING"
                self._save(record, state)
                try:
                    evidence = self.checker(record, qa_attempt=attempt)
                except Exception as exc:
                    self._hard_break(record, state, "CHECK_PROCESS_FAILED", exc)
                    return
                if not self._eligible_checks(evidence):
                    self._blocked(record, state, "deterministic checks did not produce eligible evidence", evidence)
                    return
                changed_files = evidence.get("changed_files") or evidence.get("git", {}).get("changed_files", [])
                if not self._safe_paths(changed_files):
                    self._blocked(record, state, "DIFF_SPLIT_REQUIRED: changed files are unsafe or not ticket-owned", evidence)
                    return
                diff = evidence.get("diff")
                if not isinstance(diff, str) or not diff.strip():
                    self._blocked(record, state, "BLOCKED_NEEDS_HUMAN: base-to-current Diff is empty or unavailable", evidence)
                    return

                state["state"] = "QA_RUNNING"
                qa_input = {
                    "ticket_spec": state["ticket_spec"], "prompt": state["qa_prompt"], "run": asdict(record),
                    "diff": diff, "changed_files": changed_files, "check_evidence": evidence.get("checks", []),
                    "qa_attempt": attempt, "role": "qa", "permission_mode": "read-only",
                }
                try:
                    raw = self.qa(**qa_input)
                except Exception as exc:
                    self._hard_break(record, state, "QA_PROCESS_FAILED", exc)
                    return
                verdict = raw.get("verdict") if isinstance(raw, dict) and "decision" in raw else raw
                valid, errors = validate_verdict(verdict)
                if not valid:
                    self._hard_break(record, state, "QA_MALFORMED_OUTPUT", "; ".join(errors))
                    return
                assert isinstance(verdict, dict)
                verdict_error = self._verdict_error(verdict, state["ticket_spec"])
                if verdict_error:
                    self._hard_break(record, state, "QA_MALFORMED_OUTPUT", verdict_error)
                    return
                if verdict.get("issue_key") != record.issue_key or verdict.get("run_id") != record.run_id or verdict.get("qa_attempt") != attempt:
                    self._hard_break(record, state, "QA_EVIDENCE_MISMATCH", "QA verdict identity does not match this attempt")
                    return
                state["qa_processes"].append(self._identity(raw, "qa", attempt))
                state["attempts"].append({"qa_attempt": attempt, "input_hash": self._hash(qa_input),
                                          "findings": verdict["findings"], "changed_files": changed_files,
                                          "checks": evidence.get("checks", []), "verdict": verdict})
                self._write_json(Path(record.artifact_dir) / f"qa-verdict-{attempt:02d}.json", verdict)
                if verdict["verdict"] == "BLOCKED":
                    self._blocked(record, state, "QA returned BLOCKED", evidence)
                    return
                if verdict["verdict"] == "PASS":
                    commit = self._commit(record, state["ticket_spec"], changed_files)
                    if isinstance(commit, str):
                        self._blocked(record, state, commit, evidence)
                        return
                    state.update({"state": PASS, "status": PASS, "commit": commit, "findings": None})
                    self._save(record, state)
                    self.run_manager.update_state(record, PASS)
                    return
                # The untouched finding list is the only repair input.  A fifth
                # failure consumes no additional Developer or Commit call.
                state["findings"] = verdict["findings"]
                if attempt == MAX_QA_ATTEMPTS:
                    state.update({"state": QA_EXHAUSTED, "status": QA_EXHAUSTED})
                    self._save(record, state)
                    self.run_manager.update_state(record, QA_EXHAUSTED)
                    return
                self._save(record, state)
        except Exception as exc:  # preserve a terminal artifact for unforeseen adapter faults
            self._hard_break(record, state, "LOOP_ENVIRONMENT_FAILED", exc)

    def _commit(self, record: RunRecord, ticket_spec: dict[str, Any], changed_files: list[str]) -> dict[str, str] | str:
        if not changed_files or not self._safe_paths(changed_files):
            return "BLOCKED_NEEDS_HUMAN: no safe ticket-owned files to commit"
        worktree = Path(record.worktree)
        try:
            # Stage exactly the independently observed, repository-relative set.
            result = self.git_runner(["git", "add", "--", *changed_files], cwd=worktree, capture_output=True, text=True, check=False)
            if result.returncode:
                return f"TECHNICAL_BLOCKED: git add failed: {result.stderr.strip()}"
            staged = self.git_runner(["git", "diff", "--cached", "--name-only"], cwd=worktree, capture_output=True, text=True, check=False)
            staged_files = [line for line in staged.stdout.splitlines() if line]
            if staged.returncode or set(staged_files) != set(changed_files):
                return "DIFF_SPLIT_REQUIRED: staged files differ from ticket-owned changed files"
            commit = self.git_runner(["git", "commit", "-m", f"{record.issue_key}: verified Web Run"], cwd=worktree, capture_output=True, text=True, check=False)
            if commit.returncode:
                return f"TECHNICAL_BLOCKED: git commit failed: {commit.stderr.strip()}"
            sha = self.git_runner(["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False)
            if sha.returncode:
                return "TECHNICAL_BLOCKED: cannot record Commit SHA"
            return {"branch": record.branch, "sha": sha.stdout.strip(), "changed_files": staged_files}
        except (OSError, subprocess.SubprocessError) as exc:
            return f"TECHNICAL_BLOCKED: git commit operation failed: {exc}"

    def _active_for(self, issue_key: str) -> bool:
        for path in self.run_manager.run_root.glob("*/state.json"):
            try:
                record = self.run_manager.load_run(path.parent.name)
            except Exception:
                continue
            if record.issue_key.casefold() == issue_key.casefold() and record.state == ACTIVE:
                return True
        return False

    @staticmethod
    def _verdict_error(verdict: dict[str, Any], ticket_spec: dict[str, Any]) -> str | None:
        if verdict["verdict"] == "FAIL" and not verdict["findings"]:
            return "QA FAIL has no original findings to provide to Developer"
        if verdict["verdict"] == "PASS":
            expected = {item["id"] for item in ticket_spec["acceptance_criteria"]}
            supplied = {item["id"] for item in verdict["acceptance_criteria"]}
            if supplied != expected or any(item["status"] != "PASS" or not item["evidence"] for item in verdict["acceptance_criteria"]):
                return "QA PASS lacks complete passing acceptance evidence"
        return None

    @staticmethod
    def _eligible_checks(evidence: Any) -> bool:
        return (isinstance(evidence, dict) and evidence.get("verified") is True
                and bool(evidence.get("checks")) and all(item.get("exit_code") == 0 for item in evidence["checks"]))

    @staticmethod
    def _safe_paths(paths: Any) -> bool:
        return isinstance(paths, list) and bool(paths) and all(
            isinstance(path, str) and path and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts and not path.startswith(".git/") for path in paths
        )

    def _initial_state(self, record: RunRecord, developer_prompt: str, qa_prompt: str) -> dict[str, Any]:
        return {"schema_version": "1.0", "run_id": record.run_id, "issue_key": record.issue_key,
                "state": ACTIVE, "status": ACTIVE, "ticket_spec": json.loads((Path(record.artifact_dir) / "ticket-spec.json").read_text()),
                "developer_prompt": developer_prompt, "qa_prompt": qa_prompt, "qa_attempt": 0, "findings": None,
                "attempts": [], "developer_processes": [], "qa_processes": [],
                "pre_existing_dirty_paths": self._dirty_paths(Path(record.repository))}

    def _hard_break(self, record: RunRecord, state: dict[str, Any], code: str, error: object) -> None:
        state.update({"state": HARD_BREAK, "status": HARD_BREAK, "hard_break": {"code": code, "reason": str(error)}})
        self._save(record, state)
        self.run_manager.update_state(record, HARD_BREAK)

    def _blocked(self, record: RunRecord, state: dict[str, Any], reason: str, evidence: dict[str, Any]) -> None:
        state.update({"state": BLOCKED, "status": BLOCKED, "reason": reason, "last_check_evidence": evidence})
        self._save(record, state)
        self.run_manager.update_state(record, BLOCKED)

    @staticmethod
    def _identity(output: Any, role: str, attempt: int) -> dict[str, Any]:
        identity = output.get("process_identity") if isinstance(output, dict) else None
        return {"role": role, "qa_attempt": attempt, "identity": identity or f"{role}-attempt-{attempt}"}

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def _dirty_paths(self, repository: Path) -> list[str]:
        result = self.git_runner(["git", "status", "--porcelain"], cwd=repository, capture_output=True, text=True, check=False)
        return [line[3:] for line in result.stdout.splitlines() if len(line) > 3]

    @staticmethod
    def _state_path(record: RunRecord) -> Path:
        return Path(record.artifact_dir) / "web-agent-loop-state-v1.json"

    def _load(self, record: RunRecord) -> dict[str, Any]:
        return json.loads(self._state_path(record).read_text(encoding="utf-8"))

    def _save(self, record: RunRecord, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._write_json(self._state_path(record), state)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)

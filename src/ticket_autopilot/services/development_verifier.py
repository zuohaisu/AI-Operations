"""Deterministic development verification and immutable Run evidence.

This service deliberately has no Agent, Plane, GitHub, or PR dependency.  Its
verdict is derived only from the persisted ticket contract, local Git state,
scope limits, and recorded command exit codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
from typing import Any

from ticket_autopilot.services.run_manager import RunManager, RunRecord
from ticket_autopilot.services.ticket_contract import validate_ticket_spec


EVIDENCE_SCHEMA_VERSION = "1.0"
EVIDENCE_FILENAME = "development-evidence-v1.json"
_EVIDENCE_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "development-evidence.schema.json"

VERIFIED = "VERIFIED"
FAILED_DEVELOPMENT = "FAILED_DEVELOPMENT"
BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
BLOCKED_NEEDS_HUMAN = "BLOCKED_NEEDS_HUMAN"
BLOCKED_REQUIREMENTS = "BLOCKED_REQUIREMENTS"

# A deliberately conservative escalation list.  This is a boundary check, not a
# shell sandbox: unknown commands can run only when they do not request one of
# the explicitly prohibited operation classes below.
_UNSAFE_COMMAND_PATTERNS = (
    (r"\b(?:curl|wget|ssh|scp|rsync|nc|ncat|telnet|ping)\b", "network access"),
    (r"\b(?:gh|kubectl|terraform|ansible|helm)\b", "external or production control"),
    (r"\bgit\s+(?:push|fetch|pull|clone)\b", "remote Git operation"),
    (r"\b(?:alembic|flyway)\b|\bmanage\.py\s+migrate\b|\b(?:db|database)\s+migrate\b", "migration"),
    (r"\b(?:production|\bprod\b)\b", "production target"),
    (r"\b(?:read|select)\b|--interactive\b|(?:^|\s)-i(?:\s|$)", "interactive input"),
    (r"\brm\b|\b(?:drop|truncate)\b|\bgit\s+(?:reset\s+--hard|clean|checkout\s+--|restore\b)", "irreversible operation"),
)


@dataclass(frozen=True)
class CommandEvidence:
    """One command's raw, re-readable process evidence."""

    id: str
    source: str
    command: str
    argv: list[str]
    cwd: str
    timeout_seconds: int
    started_at: str
    finished_at: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "command": self.command,
            "argv": self.argv,
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


class DevelopmentVerifier:
    """Verify one owned AIO-11 Run and persist its first immutable evidence bundle.

    The bundle name is fixed and an existing bundle is returned instead of being
    rewritten.  A later repair attempt must have a new Run attempt/artifact
    rather than overwrite evidence that an independent QA consumer may read.
    """

    def __init__(self, run_manager: RunManager, *, command_timeout_seconds: int = 60):
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        self.run_manager = run_manager
        self.command_timeout_seconds = command_timeout_seconds
        self._commands: list[CommandEvidence] = []

    def verify(self, run: RunRecord | str) -> dict[str, Any]:
        """Return the persisted deterministic verdict for an owned disposable Run."""
        record = self.run_manager.load_run(run if isinstance(run, str) else run.run_id)
        evidence_path = Path(record.artifact_dir) / EVIDENCE_FILENAME
        if evidence_path.is_file():
            return json.loads(evidence_path.read_text(encoding="utf-8"))

        self._commands = []
        ticket_spec, spec_gaps = self._load_ticket_spec(record)
        report = self._initial_report(record)
        if spec_gaps:
            report["evidence_gaps"].extend(spec_gaps)
            return self._persist(report, record, BLOCKED_REQUIREMENTS)

        git, git_gaps = self._collect_git_evidence(record)
        report["git"] = git
        report["evidence_gaps"].extend(git_gaps)
        if git_gaps:
            # A missing worktree/base/head is an environment precondition.
            return self._persist(report, record, BLOCKED_ENVIRONMENT)
        if git["head_sha"] == record.base_sha or git["new_commit_count"] == 0:
            report["evidence_gaps"].append("no new Commit after Run base SHA")
            return self._persist(report, record, BLOCKED_ENVIRONMENT)

        scope = self._scope_evidence(ticket_spec["constraints"], git["changed_files"])
        report["scope"] = scope
        if scope["violations"]:
            report["evidence_gaps"].extend(scope["violations"])
            return self._persist(report, record, BLOCKED_NEEDS_HUMAN)

        git_failures = self._git_failures(record, git)
        if git_failures:
            report["evidence_gaps"].extend(git_failures)
            return self._persist(report, record, FAILED_DEVELOPMENT)

        requested_commands = self._requested_commands(ticket_spec)
        unsafe = self._unsafe_commands(requested_commands)
        if unsafe:
            report["evidence_gaps"].extend(unsafe)
            return self._persist(report, record, BLOCKED_NEEDS_HUMAN)

        report["requested_checks"] = [item[0] for item in requested_commands]
        for command, source, criterion_id in requested_commands:
            evidence = self._run_shell(command, Path(record.worktree), source)
            entry = evidence.as_dict()
            if criterion_id is not None:
                entry["acceptance_criterion_id"] = criterion_id
            report["checks"].append(entry)
            if evidence.exit_code != 0:
                report["evidence_gaps"].append(
                    f"{source} command exited {evidence.exit_code!r}: {command}"
                )

        status = VERIFIED if not report["evidence_gaps"] else FAILED_DEVELOPMENT
        return self._persist(report, record, status)

    verify_run = verify

    def _initial_report(self, record: RunRecord) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "kind": "ticket-autopilot.development-evidence",
            "run": {
                "run_id": record.run_id,
                "issue_key": record.issue_key,
                "repository": record.repository,
                "artifact_dir": record.artifact_dir,
                "worktree": record.worktree,
                "branch": record.branch,
                "base_sha": record.base_sha,
                "attempt": record.attempt,
            },
            "status": None,
            "verified": False,
            # A future PR connector must use this Boolean, not a developer summary.
            "eligible_for_pr": False,
            "decision_inputs": ["ticket-spec", "git", "scope", "command-exit-codes"],
            "git": {},
            "scope": {"changed_files": [], "forbidden_paths": [], "max_changed_files": None, "violations": []},
            "requested_checks": [],
            "checks": [],
            "commands": self._commands,
            "evidence_gaps": [],
        }

    def _load_ticket_spec(self, record: RunRecord) -> tuple[dict[str, Any], list[str]]:
        path = Path(record.artifact_dir) / "ticket-spec.json"
        try:
            ticket_spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {}, [f"ticket-spec artifact is unreadable: {exc}"]
        valid, errors = validate_ticket_spec(ticket_spec)
        if not valid:
            return {}, ["ticket-spec artifact is invalid: " + "; ".join(errors)]
        if ticket_spec["issue_key"] != record.issue_key:
            return {}, ["ticket-spec issue_key does not match owned Run"]
        return ticket_spec, []

    def _collect_git_evidence(self, record: RunRecord) -> tuple[dict[str, Any], list[str]]:
        worktree = Path(record.worktree)
        git: dict[str, Any] = {
            "worktree_exists": worktree.is_dir(),
            "expected_branch": record.branch,
            "actual_branch": None,
            "base_sha": record.base_sha,
            "head_sha": None,
            "base_sha_resolves": False,
            "new_commit_count": 0,
            "new_commits": [],
            "diff_nonempty": False,
            "changed_files": [],
            "conflict_files": [],
        }
        gaps: list[str] = []
        if not git["worktree_exists"]:
            return git, ["worktree is missing"]

        inside = self._git(worktree, "git-worktree", "rev-parse", "--is-inside-work-tree")
        if inside.exit_code != 0 or inside.stdout.strip() != "true":
            return git, ["worktree is not a usable Git worktree"]

        branch = self._git(worktree, "git-branch", "branch", "--show-current")
        git["actual_branch"] = branch.stdout.strip() or None
        head = self._git(worktree, "git-head", "rev-parse", "HEAD")
        git["head_sha"] = head.stdout.strip() or None
        base = self._git(worktree, "git-base", "rev-parse", f"{record.base_sha}^{{commit}}")
        git["base_sha_resolves"] = base.exit_code == 0 and bool(base.stdout.strip())

        if branch.exit_code != 0 or not git["actual_branch"]:
            gaps.append("cannot determine worktree branch")
        if head.exit_code != 0 or not git["head_sha"]:
            gaps.append("cannot determine worktree HEAD SHA")
        if not git["base_sha_resolves"]:
            gaps.append("Run base SHA does not resolve in worktree")
        if gaps:
            return git, gaps

        commits = self._git(worktree, "git-new-commits", "log", "--format=%H%x00%B%x00", f"{record.base_sha}..HEAD")
        if commits.exit_code != 0:
            return git, ["cannot determine commits after Run base SHA"]
        fields = commits.stdout.split("\x00")
        for index in range(0, len(fields) - 1, 2):
            sha = fields[index].strip()
            if sha:
                git["new_commits"].append({"sha": sha, "message": fields[index + 1].strip()})
        git["new_commit_count"] = len(git["new_commits"])

        changed = self._git(worktree, "git-diff-files", "diff", "--name-only", f"{record.base_sha}..HEAD")
        if changed.exit_code != 0:
            return git, ["cannot determine base-to-HEAD changed files"]
        git["changed_files"] = [line for line in changed.stdout.splitlines() if line]

        diff = self._git(worktree, "git-diff-nonempty", "diff", "--quiet", f"{record.base_sha}..HEAD")
        if diff.exit_code not in {0, 1}:
            return git, ["cannot determine whether base-to-HEAD Diff is empty"]
        git["diff_nonempty"] = diff.exit_code == 1

        conflicts = self._git(worktree, "git-conflicts", "diff", "--name-only", "--diff-filter=U")
        if conflicts.exit_code != 0:
            return git, ["cannot determine unresolved merge conflicts"]
        git["conflict_files"] = [line for line in conflicts.stdout.splitlines() if line]
        return git, []

    @staticmethod
    def _scope_evidence(constraints: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
        forbidden_paths = constraints.get("forbidden_paths", [])
        max_changed_files = constraints.get("max_changed_files")
        violations: list[str] = []
        for path in changed_files:
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                violations.append(f"changed path is not repository-relative: {path}")
                continue
            for pattern in forbidden_paths:
                if _matches_forbidden(path, pattern):
                    violations.append(f"forbidden path changed: {path} (matches {pattern})")
        if max_changed_files is not None and len(changed_files) > max_changed_files:
            violations.append(
                f"changed file count {len(changed_files)} exceeds max_changed_files {max_changed_files}"
            )
        return {
            "changed_files": changed_files,
            "forbidden_paths": forbidden_paths,
            "max_changed_files": max_changed_files,
            "violations": violations,
        }

    @staticmethod
    def _git_failures(record: RunRecord, git: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if git["actual_branch"] != record.branch:
            failures.append("worktree branch does not match Run branch")
        if git["head_sha"] == record.base_sha:
            failures.append("no new Commit after Run base SHA")
        if git["new_commit_count"] == 0:
            failures.append("no new Commit after Run base SHA")
        if not git["diff_nonempty"]:
            failures.append("base-to-HEAD Diff is empty")
        if git["conflict_files"]:
            failures.append("unresolved merge conflicts: " + ", ".join(git["conflict_files"]))
        for commit in git["new_commits"]:
            if record.issue_key.casefold() not in commit["message"].casefold():
                failures.append(f"Commit {commit['sha']} message does not contain issue key {record.issue_key}")
        return failures

    @staticmethod
    def _requested_commands(ticket_spec: dict[str, Any]) -> list[tuple[str, str, str | None]]:
        commands: list[tuple[str, str, str | None]] = []
        for item in ticket_spec["verification"]:
            if item["type"] in {"automated", "query"}:
                commands.append((item["command"], f"verification:{item['type']}", item["acceptance_criterion_id"]))
        commands.extend((command, "required_check", None) for command in ticket_spec["required_checks"])
        return commands

    @staticmethod
    def _unsafe_commands(commands: list[tuple[str, str, str | None]]) -> list[str]:
        violations = []
        for command, source, _ in commands:
            for pattern, reason in _UNSAFE_COMMAND_PATTERNS:
                if re.search(pattern, command, flags=re.IGNORECASE):
                    violations.append(f"{source} requires human review ({reason}): {command}")
                    break
        return violations

    def _git(self, cwd: Path, source: str, *args: str) -> CommandEvidence:
        return self._run(["git", *args], shlex.join(["git", *args]), cwd, source, timeout_seconds=15)

    def _run_shell(self, command: str, cwd: Path, source: str) -> CommandEvidence:
        return self._run(["/bin/sh", "-c", command], command, cwd, source, timeout_seconds=self.command_timeout_seconds)

    def _run(
        self, argv: list[str], command: str, cwd: Path, source: str, *, timeout_seconds: int
    ) -> CommandEvidence:
        started_at = _timestamp()
        try:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code: int | None = proc.returncode
            stdout, stderr, timed_out = proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stdout, stderr, timed_out = _text(exc.stdout), _text(exc.stderr), True
            stderr = (stderr + "\n" if stderr else "") + f"timed out after {timeout_seconds} seconds"
        except OSError as exc:
            exit_code, stdout, stderr, timed_out = None, "", str(exc), False
        evidence = CommandEvidence(
            id=f"command-{len(self._commands) + 1:03d}", source=source, command=command,
            argv=argv, cwd=str(cwd), timeout_seconds=timeout_seconds, started_at=started_at,
            finished_at=_timestamp(), exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out,
        )
        self._commands.append(evidence)
        return evidence

    def _persist(self, report: dict[str, Any], record: RunRecord, status: str) -> dict[str, Any]:
        report["status"] = status
        report["verified"] = status == VERIFIED
        report["eligible_for_pr"] = status == VERIFIED
        report["commands"] = [command.as_dict() for command in self._commands]
        report["completed_at"] = _timestamp()
        target = Path(record.artifact_dir) / EVIDENCE_FILENAME
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o444)
        try:
            # link(2) is an atomic create-if-absent operation.  It avoids a second
            # concurrent verifier replacing evidence already handed to QA.
            os.link(temporary, target)
        except FileExistsError:
            return json.loads(target.read_text(encoding="utf-8"))
        finally:
            temporary.unlink(missing_ok=True)
        return report


def load_development_evidence_schema() -> dict[str, Any]:
    """Load the versioned evidence-bundle contract for a QA consumer."""
    with _EVIDENCE_SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _matches_forbidden(path: str, pattern: str) -> bool:
    """Match documented POSIX repository-relative paths and common glob forms."""
    pure_path = PurePosixPath(path)
    return (
        fnmatch.fnmatchcase(path, pattern)
        or pure_path.match(pattern)
        or (pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2])))
    )


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_development(
    run_manager: RunManager, run: RunRecord | str, *, command_timeout_seconds: int = 60
) -> dict[str, Any]:
    """Convenience entry point for a controller node; does not invoke any connector."""
    return DevelopmentVerifier(run_manager, command_timeout_seconds=command_timeout_seconds).verify(run)

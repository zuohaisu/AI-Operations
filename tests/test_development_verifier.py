"""AIO-12 acceptance evidence using only disposable temporary Git repositories."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
import tempfile

import pytest

from ticket_autopilot.services.development_verifier import (
    BLOCKED_ENVIRONMENT,
    BLOCKED_NEEDS_HUMAN,
    EVIDENCE_FILENAME,
    FAILED_DEVELOPMENT,
    load_development_evidence_schema,
    VERIFIED,
    DevelopmentVerifier,
)
from ticket_autopilot.services.run_manager import RunManager
from tests.test_run_worktree import ticket_spec as base_ticket_spec


class TemporaryRun:
    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Ticket Autopilot tests")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "initial")
        self.manager = RunManager(self.repo)

    def close(self):
        self.temp_dir.cleanup()

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, check=check, capture_output=True, text=True
        )

    def spec(self, *, verification=None, required_checks=None, constraints=None):
        value = deepcopy(base_ticket_spec())
        value["issue_key"] = "AIO-12"
        value["source_issue"]["key"] = "AIO-12"
        value["source_issue"]["title"] = "AIO-12 verifier fixture"
        value["verification"] = verification or [{
            "acceptance_criterion_id": "AC-1", "type": "automated", "command": "true",
        }]
        value["required_checks"] = required_checks or ["true"]
        if constraints:
            value["constraints"].update(constraints)
        return value

    def run(self, **spec_options):
        return self.manager.create_run(self.spec(**spec_options))

    def commit(self, record, path="change.txt", message="AIO-12 implementation"):
        worktree = Path(record.worktree)
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_text("run-owned change\n", encoding="utf-8")
        self.git("add", path, cwd=worktree)
        self.git("commit", "-m", message, cwd=worktree)


@pytest.fixture
def temporary_run():
    fixture = TemporaryRun()
    yield fixture
    fixture.close()


def verify(fixture: TemporaryRun, record):
    return DevelopmentVerifier(fixture.manager, command_timeout_seconds=5).verify(record.run_id)


def test_ac1_no_new_commit_is_blocked_environment_and_never_has_a_pr_eligibility(temporary_run):
    record = temporary_run.run()

    result = verify(temporary_run, record)

    assert result["status"] == BLOCKED_ENVIRONMENT
    assert not result["verified"]
    assert not result["eligible_for_pr"]
    assert "no new Commit" in " ".join(result["evidence_gaps"])
    assert result["checks"] == []  # Verification commands do not run after a Git precondition failure.


@pytest.mark.parametrize("case", ["empty_diff", "conflict", "bad_message"])
def test_ac2_git_failures_are_explicit_and_persisted(temporary_run, case):
    record = temporary_run.run()
    worktree = Path(record.worktree)
    if case == "empty_diff":
        temporary_run.git("commit", "--allow-empty", "-m", "AIO-12 no file change", cwd=worktree)
    else:
        temporary_run.commit(record, path="README.md", message=("wrong message" if case == "bad_message" else "AIO-12 change"))
        if case == "conflict":
            (temporary_run.repo / "README.md").write_text("main change\n", encoding="utf-8")
            temporary_run.git("add", "README.md")
            temporary_run.git("commit", "-m", "main change")
            temporary_run.git("merge", "main", cwd=worktree, check=False)

    result = verify(temporary_run, record)
    saved = json.loads((Path(record.artifact_dir) / EVIDENCE_FILENAME).read_text(encoding="utf-8"))

    assert result["status"] == FAILED_DEVELOPMENT
    assert saved == result
    gaps = " ".join(result["evidence_gaps"])
    if case == "empty_diff":
        assert "Diff is empty" in gaps
    elif case == "conflict":
        assert "unresolved merge conflicts" in gaps
    else:
        assert "does not contain issue key AIO-12" in gaps


def test_ac3_each_ticket_command_uses_worktree_timeout_and_raw_process_output(temporary_run):
    record = temporary_run.run(
        verification=[{
            "acceptance_criterion_id": "AC-1", "type": "automated",
            "command": "printf verification-out; printf verification-err >&2",
        }, {
            "acceptance_criterion_id": "AC-1", "type": "query", "command": "printf query-out",
        }],
        required_checks=["printf required-out"],
    )
    temporary_run.commit(record)

    result = verify(temporary_run, record)

    assert result["status"] == VERIFIED
    assert len(result["checks"]) == 3
    for command in result["checks"]:
        assert command["cwd"] == record.worktree
        assert command["timeout_seconds"] == 5
        assert isinstance(command["exit_code"], int)
        assert command["started_at"] <= command["finished_at"]
    assert result["checks"][0]["stdout"] == "verification-out"
    assert result["checks"][0]["stderr"] == "verification-err"
    assert result["checks"][2]["stdout"] == "required-out"


def test_ac4_failed_required_check_is_not_verified_or_pr_eligible(temporary_run):
    record = temporary_run.run(required_checks=["printf failing >&2; exit 7"])
    temporary_run.commit(record)

    result = verify(temporary_run, record)

    assert result["status"] == FAILED_DEVELOPMENT
    assert not result["verified"]
    assert not result["eligible_for_pr"]
    assert result["checks"][-1]["exit_code"] == 7
    assert result["checks"][-1]["stderr"] == "failing"


def test_ac5_happy_path_is_a_versioned_read_only_qa_consumable_bundle(temporary_run):
    record = temporary_run.run()
    temporary_run.commit(record)

    result = verify(temporary_run, record)
    path = Path(record.artifact_dir) / EVIDENCE_FILENAME
    restored = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == VERIFIED
    assert result["verified"] and result["eligible_for_pr"]
    assert restored == result
    contract = load_development_evidence_schema()
    assert restored["schema_version"] == contract["properties"]["schema_version"]["enum"][0]
    assert restored["kind"] == contract["properties"]["kind"]["enum"][0]
    assert restored["run"]["base_sha"] == record.base_sha
    assert restored["git"]["head_sha"] != record.base_sha
    assert restored["git"]["changed_files"] == ["change.txt"]
    assert restored["commands"] and restored["checks"]
    assert stat.S_IMODE(path.stat().st_mode) & 0o222 == 0


@pytest.mark.parametrize("constraints, path, expected", [
    ({"forbidden_paths": ["secrets/**"]}, "secrets/token.txt", "forbidden path changed"),
    ({"max_changed_files": 1}, "second.txt", "exceeds max_changed_files"),
])
def test_ac6_scope_limits_block_human_review_before_ticket_commands(temporary_run, constraints, path, expected):
    record = temporary_run.run(
        required_checks=["printf should-not-run"], constraints=constraints,
    )
    temporary_run.commit(record, path=("change.txt" if "max_changed_files" in constraints else path))
    if "max_changed_files" in constraints:
        temporary_run.commit(record, path=path, message="AIO-12 second change")

    result = verify(temporary_run, record)

    assert result["status"] == BLOCKED_NEEDS_HUMAN
    assert not result["eligible_for_pr"]
    assert expected in " ".join(result["scope"]["violations"])
    assert result["checks"] == []


def test_unsafe_commands_escalate_without_execution(temporary_run):
    record = temporary_run.run(required_checks=["curl https://example.invalid"])
    temporary_run.commit(record)

    result = verify(temporary_run, record)

    assert result["status"] == BLOCKED_NEEDS_HUMAN
    assert result["checks"] == []
    assert "network access" in " ".join(result["evidence_gaps"])

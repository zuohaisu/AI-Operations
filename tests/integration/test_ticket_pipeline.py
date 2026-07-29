"""AIO-13 mock-only integration evidence for the closed ticket pipeline."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile

import pytest

from ticket_autopilot.services.development_verifier import VERIFIED
from ticket_autopilot.services.run_manager import RunManager
from ticket_autopilot.services.ticket_pipeline import (
    BLOCKED_DETERMINISTIC_VERIFICATION,
    BLOCKED_ENVIRONMENT,
    BLOCKED_QA_BLOCKED,
    BLOCKED_QA_EVIDENCE,
    BLOCKED_QA_EXHAUSTED,
    BLOCKED_QA_INVALID,
    BLOCKED_QA_TIMEOUT,
    SUCCESS,
    TicketPipeline,
)
from tests.test_run_worktree import ticket_spec as fixture_ticket_spec


@pytest.fixture
def repository():
    """Use the already-tested disposable Run manager against a temporary Git repo."""
    from tests.test_development_verifier import TemporaryRun

    fixture = TemporaryRun()
    yield fixture
    fixture.close()


def spec():
    value = deepcopy(fixture_ticket_spec())
    value["issue_key"] = "AIO-13"
    value["source_issue"]["key"] = "AIO-13"
    value["source_issue"]["title"] = "AIO-13 pipeline fixture"
    return value


def evidence():
    return {
        "status": VERIFIED,
        "verified": True,
        "eligible_for_pr": True,
        "checks": [{"source": "required_check", "exit_code": 0}],
        "git": {"base_sha": "base", "head_sha": "head"},
    }


def verdict(ticket, run_id, attempt, outcome="PASS", findings=None, *, ac_evidence=True):
    return {
        "schema_version": "1.0",
        "issue_key": ticket["issue_key"],
        "run_id": run_id,
        "qa_attempt": attempt,
        "verdict": outcome,
        "acceptance_criteria": [{
            "id": item["id"],
            "status": "PASS" if outcome == "PASS" else "FAIL",
            "evidence": ["mock check evidence"] if ac_evidence else [],
        } for item in ticket["acceptance_criteria"]],
        "findings": findings or [],
        "non_blocking_comments": [],
        "recommended_next_state": "PASS" if outcome == "PASS" else "FIXING",
    }


def finding():
    return [{
        "id": "QA-1", "severity": "major", "type": "IMPLEMENTATION_DEFECT",
        "acceptance_criterion_id": "AC-1", "summary": "exact original finding",
        "evidence": {"file": "change.txt", "line": 1}, "required_fix": "make the narrow fix",
    }]


def pipeline(repository, qa_outputs, *, verifier_output=None, github_error=None, plane_error=None, calls=None):
    calls = calls if calls is not None else []
    qa_outputs = list(qa_outputs)  # parametrized fixtures must not be mutated

    def planner(**kwargs):
        calls.append(("plan", kwargs))
        return "implementation plan"

    def executor(**kwargs):
        calls.append(("execute", kwargs))
        return "developer output"

    def verifier(run):
        calls.append(("verify", run.run_id))
        return verifier_output if verifier_output is not None else evidence()

    def qa(**kwargs):
        calls.append(("qa", kwargs))
        value = qa_outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value(kwargs) if callable(value) else value

    def create_pr(**kwargs):
        calls.append(("pr", kwargs))
        if github_error:
            raise github_error
        return {"number": 13, "url": "https://example.invalid/pr/13", "draft": kwargs["draft"]}

    def update_plane(issue_id, *, state, summary):
        calls.append(("plane", {"issue_id": issue_id, "state": state, "summary": summary}))
        if plane_error:
            raise plane_error
        return {"updated": True, "state_name": state}

    return TicketPipeline(
        repository.manager, planner=planner, executor=executor, verifier=verifier,
        qa=qa, github_create_pr=create_pr, plane_update=update_plane,
        diff_provider=lambda _run, _evidence: "diff --git a/change.txt b/change.txt\n+change\n",
    ), calls


def test_ac1_verified_pass_creates_draft_pr_then_moves_plane_to_in_review_with_summary(repository):
    ticket = spec()
    p, calls = pipeline(repository, [lambda ctx: verdict(ticket, ctx["run_id"], 1)])

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == SUCCESS and result["success"]
    names = [name for name, _ in calls]
    assert names == ["plan", "execute", "verify", "qa", "pr", "plane"]
    assert calls[-2][1]["draft"] is True
    assert calls[-1][1]["state"] == "In Review"
    assert "Run:" in calls[-1][1]["summary"]
    assert "PR: https://example.invalid/pr/13" in calls[-1][1]["summary"]
    assert "Checks:" in calls[-1][1]["summary"] and "QA: PASS" in calls[-1][1]["summary"]

    # The retained terminal ledger makes repeated delivery idempotent: no new PR
    # and no duplicate Plane update are allowed.
    repeated = p.run_existing(result["run_id"])
    assert repeated == result
    assert [name for name, _ in calls].count("pr") == 1
    assert [name for name, _ in calls].count("plane") == 1


def test_ac2_fail_forwards_only_raw_findings_then_reruns_execute_verify_and_qa(repository):
    ticket, raw = spec(), finding()
    p, calls = pipeline(repository, [
        lambda ctx: verdict(ticket, ctx["run_id"], 1, "FAIL", raw),
        lambda ctx: verdict(ticket, ctx["run_id"], 2),
    ])

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == SUCCESS
    assert [name for name, _ in calls] == ["plan", "execute", "verify", "qa", "execute", "verify", "qa", "pr", "plane"]
    second_execute = [kwargs for name, kwargs in calls if name == "execute"][1]
    assert second_execute["findings"] == raw
    assert set(second_execute) == {"ticket_spec", "plan", "run", "findings"}


def test_ac3_third_qa_fail_exhausts_without_fourth_execute_or_pr(repository):
    ticket, raw = spec(), finding()
    p, calls = pipeline(repository, [
        lambda ctx: verdict(ticket, ctx["run_id"], 1, "FAIL", raw),
        lambda ctx: verdict(ticket, ctx["run_id"], 2, "FAIL", raw),
        lambda ctx: verdict(ticket, ctx["run_id"], 3, "FAIL", raw),
    ])

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == BLOCKED_QA_EXHAUSTED
    assert [name for name, _ in calls].count("execute") == 3
    assert [name for name, _ in calls].count("verify") == 3
    assert [name for name, _ in calls].count("qa") == 3
    assert "pr" not in [name for name, _ in calls]
    assert [item for item in calls if item[0] == "plane"][0][1]["state"] == "Blocked"


@pytest.mark.parametrize("case, expected", [
    ("blocked", BLOCKED_QA_BLOCKED),
    ("malformed", BLOCKED_QA_INVALID),
    ("timeout", BLOCKED_QA_TIMEOUT),
    ("missing-evidence", BLOCKED_QA_EVIDENCE),
])
def test_ac4_qa_blocked_invalid_timeout_or_missing_evidence_stops_without_fix_retry(repository, case, expected):
    ticket = spec()
    if case == "blocked":
        outputs = [lambda ctx: verdict(ticket, ctx["run_id"], 1, "BLOCKED")]
    elif case == "malformed":
        outputs = [{}]
    elif case == "timeout":
        outputs = [TimeoutError("QA timed out")]
    else:
        outputs = [lambda ctx: verdict(ticket, ctx["run_id"], 1, "PASS", ac_evidence=False)]
    p, calls = pipeline(repository, outputs)

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == expected
    assert [name for name, _ in calls].count("execute") == 1
    assert [name for name, _ in calls].count("qa") == 1
    assert "pr" not in [name for name, _ in calls]
    assert [item for item in calls if item[0] == "plane"][0][1]["state"] == "Blocked"


def test_ac5_deterministic_verify_failure_never_calls_qa_pr_or_in_review(repository):
    p, calls = pipeline(repository, [lambda ctx: pytest.fail("QA must not run")], verifier_output={"status": "FAILED_DEVELOPMENT", "verified": False, "checks": []})

    result = p.run(spec(), plane_issue_id="plane-13")

    assert result["status"] == BLOCKED_DETERMINISTIC_VERIFICATION
    assert [name for name, _ in calls] == ["plan", "execute", "verify", "plane"]
    assert calls[-1][1]["state"] == "Blocked"


@pytest.mark.parametrize("failure", ["github", "plane"])
def test_ac6_connector_failure_retains_evidence_and_never_reports_success(repository, failure):
    ticket = spec()
    p, calls = pipeline(
        repository, [lambda ctx: verdict(ticket, ctx["run_id"], 1)],
        github_error=RuntimeError("GitHub unavailable") if failure == "github" else None,
        plane_error=RuntimeError("Plane unavailable") if failure == "plane" else None,
    )

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == BLOCKED_ENVIRONMENT and not result["success"]
    path = Path(repository.repo / ".ticket-autopilot" / "runs" / result["run_id"] / "ticket-pipeline-state-v1.json")
    assert path.is_file() and "eligible_for_pr" in path.read_text(encoding="utf-8")
    names = [name for name, _ in calls]
    if failure == "github":
        assert names == ["plan", "execute", "verify", "qa", "pr", "plane"]
        assert calls[-1][1]["state"] == "Blocked"
    else:
        assert names == ["plan", "execute", "verify", "qa", "pr", "plane"]


def test_ac7_safety_red_lines_have_no_merge_push_main_or_done_path(repository):
    ticket = spec()
    p, calls = pipeline(repository, [lambda ctx: verdict(ticket, ctx["run_id"], 1)])

    result = p.run(ticket, plane_issue_id="plane-13")

    assert result["status"] == SUCCESS
    # The only external actions are the instrumented draft-PR and In Review
    # state write; neither connector exposes merge, push, or Done operations.
    assert [name for name, _ in calls][-2:] == ["pr", "plane"]
    assert all(payload["state"] != "Done" for name, payload in calls if name == "plane")
    pr = [payload for name, payload in calls if name == "pr"][0]
    assert pr["draft"] is True and pr["head"] != pr["base"]

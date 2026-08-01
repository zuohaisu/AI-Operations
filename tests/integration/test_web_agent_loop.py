"""AIO-19 isolated Web loop evidence; all Agents and Git repositories are fake/local."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ticket_autopilot.services.web_agent_loop import HARD_BREAK, PASS, QA_EXHAUSTED, WebAgentLoop
from tests.test_development_verifier import TemporaryRun
from tests.test_run_worktree import ticket_spec as base_ticket_spec


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs): self.target, self.args = target, args
    def start(self): self.target(*self.args)


def spec():
    value = deepcopy(base_ticket_spec())
    value["issue_key"] = value["source_issue"]["key"] = "AIO-19"
    return value


def verdict(ticket, run_id, attempt, outcome="PASS"):
    return {"schema_version": "1.0", "issue_key": ticket["issue_key"], "run_id": run_id,
            "qa_attempt": attempt, "verdict": outcome,
            "acceptance_criteria": [{"id": item["id"], "status": "PASS" if outcome == "PASS" else "FAIL", "evidence": ["fake"]} for item in ticket["acceptance_criteria"]],
            "findings": [] if outcome == "PASS" else [{"id": "QA-1", "severity": "major", "type": "bug", "acceptance_criterion_id": "AC-1", "summary": "original", "evidence": {"file": "change.txt"}, "required_fix": "fix"}],
            "non_blocking_comments": [], "recommended_next_state": "PASS" if outcome == "PASS" else "FIXING"}


def loop(fixture, outcomes, calls, *, unsafe=False):
    def developer(**kwargs):
        calls.append(("developer", kwargs))
        (Path(kwargs["run"]["worktree"]) / "change.txt").write_text("changed", encoding="utf-8")
        return {"process_identity": f"dev-{len([x for x in calls if x[0] == 'developer'])}"}
    def checker(run, *, qa_attempt):
        calls.append(("checks", qa_attempt))
        return {"verified": True, "checks": [{"exit_code": 0}], "changed_files": ["../foreign" if unsafe else "change.txt"], "diff": "diff --git a/change.txt b/change.txt\n+changed\n"}
    def qa(**kwargs):
        calls.append(("qa", kwargs))
        assert kwargs["verification_evidence"]["verified"] is True
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException): raise outcome
        return verdict(spec(), kwargs["run"]["run_id"], kwargs["qa_attempt"], outcome)
    return WebAgentLoop(fixture.manager, developer=developer, checker=checker, qa=qa, thread_factory=ImmediateThread)


def test_happy_one_fix_and_commit_after_pass():
    fixture, calls = TemporaryRun(), []
    try:
        service = loop(fixture, ["FAIL", "PASS"], calls)
        result = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        state = service.status(result["run_id"])
        assert state["status"] == PASS and state["commit"]["changed_files"] == ["change.txt"]
        assert [name for name, _ in calls] == ["developer", "checks", "qa", "developer", "checks", "qa"]
        assert calls[3][1]["findings"] == state["attempts"][0]["findings"]  # original QA findings only
    finally: fixture.close()


def test_fifth_pass_and_fifth_fail_have_exactly_five_qa_attempts():
    for outcomes, expected in [(["FAIL"] * 4 + ["PASS"], PASS), (["FAIL"] * 5, QA_EXHAUSTED)]:
        fixture, calls = TemporaryRun(), []
        try:
            result = loop(fixture, outcomes, calls).start(spec(), developer_prompt="dev", qa_prompt="qa")
            state_path = fixture.repo / ".ticket-autopilot" / "runs" / result["run_id"] / "web-agent-loop-state-v1.json"
            import json
            state = json.loads(state_path.read_text())
            assert state["status"] == expected and [a["qa_attempt"] for a in state["attempts"]] == [1, 2, 3, 4, 5]
            assert [name for name, _ in calls].count("developer") == 5
            assert "commit" in state if expected == PASS else "commit" not in state
        finally: fixture.close()


def test_process_failure_and_unsafe_diff_are_not_qa_failures_or_commits():
    fixture, calls = TemporaryRun(), []
    try:
        result = loop(fixture, [RuntimeError("QA broken")], calls).start(spec(), developer_prompt="dev", qa_prompt="qa")
        import json
        state = json.loads((fixture.repo / ".ticket-autopilot" / "runs" / result["run_id"] / "web-agent-loop-state-v1.json").read_text())
        assert state["status"] == HARD_BREAK and state["qa_attempt"] == 1 and not state["attempts"]
    finally: fixture.close()
    fixture, calls = TemporaryRun(), []
    try:
        result = loop(fixture, ["PASS"], calls, unsafe=True).start(spec(), developer_prompt="dev", qa_prompt="qa")
        state = __import__("json").loads((fixture.repo / ".ticket-autopilot" / "runs" / result["run_id"] / "web-agent-loop-state-v1.json").read_text())
        assert state["status"] == "BLOCKED" and not [name for name, _ in calls if name == "qa"] and "commit" not in state
    finally: fixture.close()


def test_duplicate_active_run_is_rejected_before_second_agent_or_worktree():
    fixture, calls = TemporaryRun(), []
    try:
        class HeldThread(ImmediateThread):
            def start(self): pass
        service = loop(fixture, ["PASS"], calls)
        service.thread_factory = HeldThread
        first = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        second = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        assert first["status"] == "ACTIVE" and second["status"] == "BLOCKED" and not calls
    finally: fixture.close()

"""AIO-20 Timeline evidence tests: all collaborators are local fakes."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ticket_autopilot.services.delivery_policy import DeliveryAuthorizationError
from ticket_autopilot.services.web_agent_loop import HARD_BREAK, STOPPED, WebAgentLoop
from tests.test_development_verifier import TemporaryRun
from tests.test_run_worktree import ticket_spec as base_ticket_spec


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class HeldThread(ImmediateThread):
    def start(self): pass


def spec():
    value = deepcopy(base_ticket_spec())
    value["issue_key"] = value["source_issue"]["key"] = "AIO-20"
    return value


def verdict(run_id: str, attempt: int, outcome: str = "PASS") -> dict:
    ticket = spec()
    return {"schema_version": "1.0", "issue_key": ticket["issue_key"], "run_id": run_id, "qa_attempt": attempt,
            "verdict": outcome, "acceptance_criteria": [{"id": item["id"], "status": "PASS" if outcome == "PASS" else "FAIL", "evidence": ["local fake"]} for item in ticket["acceptance_criteria"]],
            "findings": [] if outcome == "PASS" else [{"id": "F-1", "severity": "major", "type": "bug", "acceptance_criterion_id": "AC-1", "summary": "long finding " * 80, "evidence": {}, "required_fix": "fix"}],
            "non_blocking_comments": [], "recommended_next_state": outcome}


def loop(fixture, outcomes, *, secret: str = ""):
    def developer(**kwargs):
        (Path(kwargs["run"]["worktree"]) / "change.txt").write_text("changed", encoding="utf-8")
        return {"process_identity": "local-developer"}
    def checker(run, *, qa_attempt):
        return {"verified": True, "checks": [{"command": "local", "exit_code": 0}], "changed_files": ["change.txt"], "diff": "diff --git a/change.txt b/change.txt\n+changed\n"}
    def qa(**kwargs):
        value = outcomes.pop(0)
        if isinstance(value, BaseException): raise value
        return verdict(kwargs["run"]["run_id"], kwargs["qa_attempt"], value)
    return WebAgentLoop(fixture.manager, developer=developer, checker=checker, qa=qa, thread_factory=ImmediateThread, known_secrets=(secret,))


def owner(action: str, *, actor_type: str = "repository_owner") -> dict:
    return {"actor": "repo-owner", "actor_type": actor_type, "action": action, "approved": True,
            "approved_at": "2026-07-30T12:00:00Z", "reason": "explicit local owner decision"}


def test_timeline_uses_append_only_artifact_for_roles_rounds_prompts_findings_and_commit():
    fixture = TemporaryRun()
    try:
        service = loop(fixture, ["FAIL", "PASS"])
        run = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        timeline = service.timeline(run["run_id"])
        events = timeline["events"]
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert [(event["stage"], event["role"], event["round"]) for event in events if event["event_type"] in {"prompt_sources_recorded", "agent_started", "qa_verdict_recorded", "commit_recorded"}] == [
            ("planner", "planner", 0), ("development", "developer", 1), ("qa", "qa", 1), ("qa", "qa", 1),
            ("development", "developer", 2), ("qa", "qa", 2), ("qa", "qa", 2), ("commit", "controller", 2),
        ]
        qa_fail = next(event for event in events if event["event_type"] == "qa_verdict_recorded" and event["status"] == "FAIL")
        assert qa_fail["details"]["findings"][0]["summary"].startswith("long finding")
        commit = next(event for event in events if event["event_type"] == "commit_recorded")
        assert commit["details"]["sha"] == timeline["snapshot"]["commit"]["sha"]
        assert timeline["snapshot"]["status"] == "PASS"
        assert timeline["process_output"]
        assert any(entry["stage"] == "commit" for entry in timeline["process_output"])
    finally:
        fixture.close()


def test_canonical_delivery_states_are_persisted_events_not_frontend_inference():
    fixture = TemporaryRun()
    try:
        record = fixture.manager.create_run(spec())
        for state in ("QA_PENDING", "HUMAN_VISUAL_REVIEW_PENDING", "READY_FOR_REVIEW", "DIFF_SPLIT_REQUIRED", "USER_OVERRIDE_APPROVED", "MERGE_AUTHORIZED_BY_USER", "TECHNICAL_BLOCKED"):
            fixture.manager.append_event(record, stage="delivery", role="controller", status=state, event_type="test_delivery_state")
        assert {event["status"] for event in fixture.manager.events(record)} >= {"QA_PENDING", "HUMAN_VISUAL_REVIEW_PENDING", "READY_FOR_REVIEW", "DIFF_SPLIT_REQUIRED", "USER_OVERRIDE_APPROVED", "MERGE_AUTHORIZED_BY_USER", "TECHNICAL_BLOCKED"}
    finally:
        fixture.close()


def test_hard_break_and_raw_event_artifacts_redact_known_secret():
    fixture, secret = TemporaryRun(), "aio20-super-secret"
    try:
        service = loop(fixture, [RuntimeError(f"QA broken: {secret}")], secret=secret)
        run = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        timeline = service.timeline(run["run_id"])
        assert timeline["snapshot"]["status"] == HARD_BREAK
        hard_break = next(event for event in timeline["events"] if event["event_type"] == "hard_break")
        assert hard_break["details"]["role"] == "qa" and hard_break["details"]["worktree"]
        artifact = Path(fixture.manager.load_run(run["run_id"]).artifact_dir)
        assert secret not in (artifact / "events.jsonl").read_text()
        assert secret not in (artifact / "web-agent-loop-state-v1.json").read_text()
        assert secret not in str(timeline)
    finally:
        fixture.close()


def test_owner_five_actions_are_audited_without_rewriting_original_gate_and_agents_are_rejected():
    fixture = TemporaryRun()
    try:
        service = loop(fixture, ["PASS"])
        run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
        original = service.status(run_id)["status"]
        for action in ("visual_accept", "override_gate", "push_feature_branch", "create_draft_pr", "merge"):
            result = service.record_owner_action(run_id, owner(action))
            assert result["original_status"] == original
        with pytest.raises(DeliveryAuthorizationError):
            service.record_owner_action(run_id, owner("merge", actor_type="developer_agent"))
        actions = [event for event in service.timeline(run_id)["events"] if event["event_type"] == "owner_action_recorded"]
        assert [event["details"]["action"] for event in actions] == ["visual_accept", "override_gate", "push_feature_branch", "create_draft_pr", "merge"]
        assert all(set(("actor", "action", "approved_at", "reason")) <= set(event["details"]) for event in actions)
    finally:
        fixture.close()


def test_stop_signals_only_registered_owned_group_and_retains_artifacts():
    fixture, terminated = TemporaryRun(), []
    try:
        service = loop(fixture, ["PASS"])
        service.thread_factory = HeldThread
        service.terminate_group = terminated.append
        service.owns_process_group = lambda pid, group: (pid, group) == (401, 402)
        run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
        service.register_owned_process_group(run_id, pid=401, process_group=402)
        result = service.stop(run_id)
        assert result["status"] == STOPPED and terminated == [402]
        assert Path(result["artifact_dir"]).is_dir()
        assert service.status(run_id)["status"] == STOPPED
    finally:
        fixture.close()

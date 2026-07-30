"""AIO-20 retry and authority integration evidence without any remote system."""
from __future__ import annotations

from pathlib import Path

from ticket_autopilot.services.web_agent_loop import ACTIVE, HARD_BREAK, PASS
from tests.test_development_verifier import TemporaryRun
from tests.test_web_run_tracking import loop, spec, verdict


def test_retry_keeps_same_run_and_only_appends_history_before_rechecking_and_qa():
    fixture = TemporaryRun()
    try:
        service = loop(fixture, [RuntimeError("local QA process failed")])
        result = service.start(spec(), developer_prompt="dev", qa_prompt="qa")
        run_id = result["run_id"]
        before = service.timeline(run_id)["events"]
        assert service.status(run_id)["status"] == HARD_BREAK

        def passing_qa(**kwargs):
            return verdict(kwargs["run"]["run_id"], kwargs["qa_attempt"], "PASS")
        service.qa = passing_qa
        retried = service.retry_current_stage(run_id)
        after = service.timeline(run_id)["events"]

        assert retried == {"run_id": run_id, "status": ACTIVE, "retry_from_stage": "qa"}
        assert service.status(run_id)["status"] == PASS
        assert len(after) > len(before)
        assert after[:len(before)] == before
        retry_index = next(index for index, event in enumerate(after) if event["event_type"] == "retry_requested")
        assert [event["event_type"] for event in after[retry_index + 1:]].count("checks_completed") == 1
        assert [event["event_type"] for event in after[retry_index + 1:]].count("qa_verdict_recorded") == 1
        assert Path(fixture.manager.load_run(run_id).artifact_dir, "events.jsonl").is_file()
    finally:
        fixture.close()

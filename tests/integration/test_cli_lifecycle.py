"""AIO-14 isolated product lifecycle tests; collaborators are all local fakes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from ticket_autopilot.services.ticket_controller import TicketController
from tests.test_development_verifier import TemporaryRun
from tests.test_run_worktree import ticket_spec


@pytest.fixture
def isolated_controller():
    fixture = TemporaryRun()
    env = {
        "PLANE_API_KEY": "plane-test-key",
        "GITHUB_TOKEN": "github-test-token",
        "TICKET_AUTOPILOT_PLANNER_CLI": "planner-test",
        "TICKET_AUTOPILOT_DEVELOPER_CLI": "developer-test",
        "TICKET_AUTOPILOT_QA_CLI": "qa-test",
    }
    controller = TicketController(
        fixture.repo, environ=env, which=lambda _name: "/fake/agent", terminate_group=lambda _group: None,
    )
    yield fixture, controller
    fixture.close()


def _issue():
    spec = ticket_spec()
    spec["issue_key"] = "AIO-14"
    spec["source_issue"]["key"] = "AIO-14"
    # The controller's Plane intake is patched below, but preflight needs the
    # structured original issue rather than the already-mapped ticket-spec.
    description = """## Goal
Create the CLI.

## Scope
CLI wiring.

## Out of scope
Network test.

## Risk Tier
R1

## Acceptance Criteria
- AC-1: CLI works.

## Verification
- AC-1: automated: `true`

## Repository
owner/repository

## Required Checks
- `true`

## Constraints
- max_fix_attempts: 2
- allow_main_push: false
"""
    return {"id": "plane-14", "identifier": "AIO-14", "name": "AIO-14 CLI", "description": description, "state": "In Progress"}


def test_run_uses_real_pipeline_interface_and_retains_run_id(isolated_controller):
    _fixture, controller = isolated_controller
    calls = []

    class Pipeline:
        def __init__(self, manager, **kwargs):
            calls.append((manager, kwargs))

        def run_existing(self, record, *, ticket_spec, plane_issue_id):
            assert record.issue_key == "AIO-14"
            assert ticket_spec["issue_key"] == "AIO-14"
            assert plane_issue_id == "plane-14"
            return {"run_id": record.run_id, "status": "IN_REVIEW", "success": True, "pr": {"url": "https://example.invalid/14"}}

    with mock.patch("ticket_autopilot.services.ticket_controller.plane.fetch_issue_by_identifier", return_value=_issue()):
        controller.pipeline_factory = Pipeline
        result = controller.run("AIO-14")

    assert result["status"] == "IN_REVIEW"
    assert result["run_id"]
    assert len(calls) == 1
    lifecycle = Path(_fixture.repo / ".ticket-autopilot" / "runs" / result["run_id"] / "controller-lifecycle-v1.json")
    assert json.loads(lifecycle.read_text())["status"] == "COMPLETED"


def test_status_cancel_and_cleanup_use_owned_run_only(isolated_controller):
    fixture, controller = isolated_controller
    spec = ticket_spec()
    spec["issue_key"] = spec["source_issue"]["key"] = "AIO-14"
    record = fixture.manager.create_run(spec)
    fixture.commit(record, message="AIO-14 disposable change")
    controller._write_lifecycle(record, "ACTIVE", controller_pid=123, process_group=456)

    with mock.patch.object(controller, "_owns_live_process", return_value=True):
        cancelled = controller.cancel("AIO-14", run_id=record.run_id)
    assert cancelled["status"] == "CANCELLED"
    assert fixture.manager.load_run(record.run_id).state == "CANCELLED"

    state = controller.status("AIO-14", run_id=record.run_id)
    assert set(("status", "node", "worktree", "branch", "pr", "attempt", "updated_at", "blocked_reason")) <= state.keys()
    assert state["status"] == "CANCELLED"

    cleaned = controller.cleanup("AIO-14", run_id=record.run_id)
    assert cleaned["status"] == "CLEANED"
    assert not Path(record.worktree).exists()
    assert Path(record.artifact_dir, "controller.log").exists()


def test_active_run_prevents_second_agent_workflow_before_creation(isolated_controller):
    fixture, controller = isolated_controller
    spec = ticket_spec()
    spec["issue_key"] = spec["source_issue"]["key"] = "AIO-14"
    record = fixture.manager.create_run(spec)
    controller._write_lifecycle(record, "ACTIVE", controller_pid=1, process_group=1)

    with mock.patch("ticket_autopilot.services.ticket_controller.plane.fetch_issue_by_identifier", return_value=_issue()):
        with mock.patch.object(controller, "_build_pipeline") as build:
            result = controller.run("AIO-14")
    assert result["status"] == "ACTIVE"
    build.assert_not_called()
    assert fixture.manager.load_run(record.run_id).run_id == record.run_id

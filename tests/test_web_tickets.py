"""AIO-18 ticket-panel API logic tests with fake Plane and Planner only."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from ticket_autopilot.connectors import plane
from ticket_autopilot.web import LocalConfig, TicketBoard


def raw(state_group: str = "started", *, sequence: int = 18, identifier: str = "AIO") -> dict:
    return {
        "id": f"item-{state_group}", "name": "AIO ticket", "description": None, "identifier": None,
        "description_html": """<h2>Goal</h2><p>deterministic intake</p><h2>Scope</h2><ul><li>Impact closure covers callers and consumers, triggered guards, executable dependencies, Given when then behavioral AC, observed checked-at semantic mapping, and global serial resource 127.0.0.1:8765.</li></ul>
<h2>Out-of-scope</h2><ul><li>no PR</li></ul><h2>Risk Tier</h2><p>R1</p><h2>Acceptance Criteria</h2><ul><li>AC-1: works</li></ul>
<h2>Verification</h2><ul><li>AC-1: automated: <code>pytest -q</code></li></ul><h2>Repository</h2><p><code>zuohaisu/AI-Operations</code></p>
<h2>Required Checks</h2><ul><li><code>pytest -q</code></li></ul><h2>Constraints</h2><ul><li>max_fix_attempts: 0</li><li>allow_main_push: false</li></ul>""",
        "description_stripped": "flat preview", "sequence_id": sequence,
        "project": {"identifier": identifier}, "state": {"id": f"{state_group}-id", "group": state_group},
        "priority": "high",
    }


def board(tmp_path: Path, *, planner=None) -> TicketBoard:
    settings = LocalConfig(tmp_path / "home")
    settings.save({"plane": {"workspace": "hspace", "project": "project", "api_key": "secret"}})
    (tmp_path / "tasks").mkdir()
    return TicketBoard(settings, repository=tmp_path, planner=planner)


def test_lists_only_incomplete_plane_tickets_and_preserves_v2_fields(tmp_path: Path):
    service = board(tmp_path)
    items = [plane.normalize_work_item(raw(group)) for group in ("backlog", "unstarted", "started", "completed", "cancelled")]
    with mock.patch("ticket_autopilot.web.plane.list_work_items", return_value=items):
        result = service.list()

    assert [ticket["state"]["group"] for ticket in result["tickets"]] == ["backlog", "unstarted", "started"]
    assert result["tickets"][2]["identifier"] == "AIO-18"
    assert result["tickets"][2]["eligible"]


def test_ineligible_or_active_ticket_cannot_start_developer_or_qa(tmp_path: Path):
    service = board(tmp_path)
    completed = plane.normalize_work_item(raw("completed"))
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=completed):
        result = service.prepare(completed["id"])
    assert result == {"status": "BLOCKED_REQUIREMENTS", "reason": "Plane state group completed is not eligible for a Run", "developer_calls": 0, "qa_calls": 0}

    active = tmp_path / ".ticket-autopilot" / "runs" / "other"
    active.mkdir(parents=True)
    (active / "state.json").write_text('{"state":"ACTIVE"}', encoding="utf-8")
    started = plane.normalize_work_item(raw())
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=started):
        result = service.prepare(started["id"])
    assert result["status"] == "BLOCKED_REQUIREMENTS"
    assert result["developer_calls"] == result["qa_calls"] == 0

    wrong_project = plane.normalize_work_item(raw())
    wrong_project["project"]["id"] = "different-project"
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=wrong_project):
        result = service.prepare(wrong_project["id"])
    assert result["status"] == "BLOCKED_REQUIREMENTS"
    assert "project does not match" in result["reason"]
    assert result["developer_calls"] == result["qa_calls"] == 0


def test_run_returns_owned_run_id_without_waiting_for_agent_work(tmp_path: Path):
    calls = []

    class FakeLoop:
        def start(self, ticket_spec, *, developer_prompt, qa_prompt):
            calls.append((ticket_spec, developer_prompt, qa_prompt))
            return {"status": "ACTIVE", "run_id": "aio-19-fake"}

    service = board(tmp_path)
    (tmp_path / "tasks" / "AIO-018-dev-prompt.md").write_text("dev", encoding="utf-8")
    (tmp_path / "tasks" / "AIO-018-acceptance-prompt.md").write_text("qa", encoding="utf-8")
    service.web_loop_factory = lambda **_kwargs: FakeLoop()
    started = plane.normalize_work_item(raw())
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=started):
        result = service.run(started["id"])

    assert result == {"status": "ACTIVE", "run_id": "aio-19-fake"}
    assert calls and calls[0][0]["issue_key"] == "AIO-18" and calls[0][1:] == ("dev", "qa")


def test_invalid_v2_semantics_are_not_listed_or_sent_to_planner(tmp_path: Path):
    service = board(tmp_path, planner=mock.Mock())
    invalid = raw("started", identifier="")
    with mock.patch("ticket_autopilot.web.plane.list_work_items", return_value=[]):
        assert service.list() == {"tickets": []}
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", side_effect=plane.PlaneAPIError("unknown Plane state group")):
        try:
            service.prepare("bad")
        except plane.PlaneAPIError:
            pass
    unready = plane.normalize_work_item(raw())
    unready["description"] = unready["description"].replace("Impact closure", "closure")
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=unready):
        result = service.prepare(unready["id"])
    assert result["status"] == "BLOCKED_REQUIREMENTS"
    assert "impact closure" in result["reason"]
    service.planner.assert_not_called()

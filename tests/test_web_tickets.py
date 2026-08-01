"""AIO-18 ticket-panel API logic tests with fake Plane and Planner only."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from ticket_autopilot.connectors import plane
from ticket_autopilot.web import LocalConfig, TicketBoard, _bind_agent_inputs, _qa_python_environment


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
        def start(self, ticket_spec, *, developer_prompt, qa_prompt, prompt_sources):
            calls.append((ticket_spec, developer_prompt, qa_prompt, prompt_sources))
            return {"status": "ACTIVE", "run_id": "aio-19-fake"}

    service = board(tmp_path)
    (tmp_path / "tasks" / "AIO-018-dev-prompt.md").write_text("dev", encoding="utf-8")
    (tmp_path / "tasks" / "AIO-018-acceptance-prompt.md").write_text("qa", encoding="utf-8")
    service.web_loop_factory = lambda **_kwargs: FakeLoop()
    started = plane.normalize_work_item(raw())
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=started):
        result = service.run(started["id"])

    assert result == {"status": "ACTIVE", "run_id": "aio-19-fake"}
    assert calls and calls[0][0]["issue_key"] == "AIO-18"
    assert calls[0][1:3] == ("dev", "qa")
    assert calls[0][3]["dev"]["source"] == "existing_file"


def test_web_run_request_returns_observable_operation_before_preparation(tmp_path: Path):
    service = board(tmp_path)

    class HeldThread:
        def __init__(self, *, target, args, **_kwargs):
            self.target, self.args = target, args

        def start(self):
            return None

    with mock.patch("ticket_autopilot.web.threading.Thread", HeldThread):
        result = service.start_run("plane-item-18")

    assert result["status"] == "PREPARING"
    assert result["run_id"] is None
    operation = service.operation(result["operation_id"])
    assert operation["stage"] == "planner"
    assert operation["process_output"][0]["message"].startswith("Run request accepted")


def test_single_run_action_prepares_missing_prompts_before_agents(tmp_path: Path):
    planner_calls = []
    loop_calls = []

    def planner(**kwargs):
        planner_calls.append(kwargs)
        return {
            "dev": "立即执行: Developer handles AIO-18 in zuohaisu/AI-Operations with Diff attribution, dirty-tree discipline, and a visual gate.",
            "acceptance": "立即执行: independent QA handles AIO-18 in zuohaisu/AI-Operations with Diff attribution, dirty-tree discipline, and a visual gate.",
        }

    class FakeLoop:
        def start(self, ticket_spec, *, developer_prompt, qa_prompt, prompt_sources):
            loop_calls.append((ticket_spec, developer_prompt, qa_prompt, prompt_sources))
            return {"status": "ACTIVE", "run_id": "aio-18-one-click"}

    service = board(tmp_path, planner=planner)
    service.web_loop_factory = lambda **_kwargs: FakeLoop()
    started = plane.normalize_work_item(raw())
    with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=started):
        result = service.run(started["id"])

    assert result["run_id"] == "aio-18-one-click"
    assert result["preparation"]["planner_outcome"] == "generated"
    assert result["preparation"]["planner_attempts"] == 1
    assert len(planner_calls) == 1
    assert len(loop_calls) == 1
    assert loop_calls[0][1].startswith("立即执行")
    assert loop_calls[0][2].startswith("立即执行")
    assert loop_calls[0][3]["dev"]["source"] == "planner_generated"


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


def test_agent_runtime_contract_replaces_source_checkout_with_owned_worktree(tmp_path: Path):
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    spec = {
        "repository": str(source),
        "source_issue": {"description": f"Only edit {source}/docs/file.md"},
    }
    prompt = f"Developer must work in {source}."

    bound_spec, bound_prompt = _bind_agent_inputs(
        spec, prompt, repository=source, worktree=worktree,
    )

    assert bound_spec["repository"] == str(worktree.resolve())
    assert str(source.resolve()) not in str(bound_spec)
    assert str(source.resolve()) not in bound_prompt
    assert str(worktree.resolve()) in bound_prompt


def test_qa_gets_project_python_at_a_worktree_local_path(tmp_path: Path):
    repository = tmp_path / "repository"
    worktree = tmp_path / "worktree"
    (repository / ".venv" / "bin").mkdir(parents=True)
    (repository / ".venv" / "bin" / "python").write_text("python", encoding="utf-8")
    worktree.mkdir()

    with _qa_python_environment(repository, worktree) as python:
        assert python == str(worktree / ".venv" / "bin" / "python")
        assert (worktree / ".venv").is_symlink()

    assert not (worktree / ".venv").exists()

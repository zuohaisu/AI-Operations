"""AIO-24 session orchestration tests: builder session flags, ledger, degradation.

CLI calls are always faked.  Assertions cover per-role session continuity,
the structural impossibility of a wildcard resume, and every recorded
(never silent) degradation path.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from ticket_autopilot.services.agent_catalog import AgentCatalog, CatalogError
from ticket_autopilot.services.agent_sessions import (
    LEDGER_FILENAME,
    SessionLedger,
    parse_codex_session_id,
)


def _catalog(tmp_path: Path) -> AgentCatalog:
    codex_config = tmp_path / "config.toml"
    codex_config.write_text('model = "gpt-5.6-terra"\n')
    outputs = {
        ("codex", "--version"): "codex-cli 0.145.0\n",
        ("claude", "--version"): "2.1.220\n",
        ("claude", "--help"): "--effort <effort> level (low, medium, high)\n",
        ("qodercli", "--version"): "1.1.9\n",
        ("qodercli", "--list-models"): "MODEL\nUltimate\n",
    }

    def runner(cmd, **_kwargs):
        stdout = outputs.get(tuple(cmd))
        return subprocess.CompletedProcess(cmd, 0 if stdout is not None else 1, stdout=stdout or "", stderr="")

    return AgentCatalog(runner=runner, which=lambda command: f"/bin/{command}",
                        codex_config_path=codex_config)


def _profile(provider: str) -> dict[str, str]:
    return {"provider": provider, "model": "", "reasoning": ""}


def test_session_modes_map_to_provider_flags(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    session_id = str(uuid.uuid4())

    new_codex = catalog.build_agent(_profile("codex"), role="developer", cwd="/w",
                                    allowed_roots=["/w"], session={"mode": "new"})
    assert new_codex["argv"][:2] == ["codex", "exec"]
    assert "--json" in new_codex["argv"]
    assert "--ephemeral" not in new_codex["argv"]

    resume_codex = catalog.build_agent(_profile("codex"), role="developer", cwd="/w",
                                       allowed_roots=["/w"], session={"mode": "resume", "session_id": "thread-abc.123"})
    assert resume_codex["argv"][:4] == ["codex", "exec", "resume", "thread-abc.123"]
    assert "--json" not in resume_codex["argv"]
    assert "--last" not in resume_codex["argv"]

    new_claude = catalog.build_agent(_profile("claude"), role="developer", cwd="/w",
                                     allowed_roots=["/w"], session={"mode": "new", "session_id": session_id})
    assert new_claude["extra_args"] == ["--session-id", session_id]

    resume_qoder = catalog.build_agent(_profile("qodercli"), role="developer", cwd="/w",
                                       allowed_roots=["/w"], session={"mode": "resume", "session_id": session_id})
    assert resume_qoder["extra_args"] == ["-r", session_id]

    ephemeral_qa = catalog.build_agent(_profile("qodercli"), role="qa", cwd="/w",
                                       allowed_roots=["/w"], session={"mode": "ephemeral"})
    assert ephemeral_qa["extra_args"][-1] == "--no-session-persistence"


def test_wildcard_or_invalid_resume_is_structurally_impossible(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    for bad in ({"mode": "resume"}, {"mode": "resume", "session_id": ""},
                {"mode": "resume", "session_id": "--last"},
                {"mode": "resume", "session_id": "id with spaces"},
                {"mode": "latest"}):
        with pytest.raises(CatalogError):
            catalog.build_agent(_profile("codex"), role="developer", cwd="/w",
                                allowed_roots=["/w"], session=bad)
    with pytest.raises(CatalogError, match="pre-generated session id"):
        catalog.build_agent(_profile("claude"), role="developer", cwd="/w",
                            allowed_roots=["/w"], session={"mode": "new"})


def test_parse_codex_session_id_tolerates_noise_and_degrades_to_none() -> None:
    output = "\n".join([
        "not json at all",
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "thread.started", "thread_id": "0198-abc-def"}),
        json.dumps({"type": "item.completed", "item": {"text": "done"}}),
    ])
    assert parse_codex_session_id(output) == "0198-abc-def"
    assert parse_codex_session_id("plain text output") is None
    assert parse_codex_session_id(json.dumps({"thread_id": "--last"})) is None
    assert parse_codex_session_id(None) is None
    nested = json.dumps({"event": {"session": {"session_id": "sess-42"}}})
    assert parse_codex_session_id(nested) == "sess-42"


def test_session_ledger_round_trip(tmp_path: Path) -> None:
    ledger = SessionLedger(tmp_path)
    assert ledger.get("developer") is None
    entry = ledger.record("developer", {"role": "developer", "provider": "claude", "session_id": "abc"})
    assert entry["session_id"] == "abc"
    assert SessionLedger(tmp_path).get("developer")["provider"] == "claude"
    ledger.record("qa", {"role": "qa", "session_id": None})
    stored = json.loads((tmp_path / LEDGER_FILENAME).read_text())
    assert set(stored["sessions"]) == {"developer", "qa"}


class _LoopHarness:
    """Drive the web developer/qa wrappers with faked CLI + event capture."""

    def __init__(self, tmp_path: Path, provider: str, cli_outputs: list):
        import ticket_autopilot.web as web

        self.tmp_path = tmp_path
        self.events: list[dict] = []
        self.calls: list[dict] = []
        self.cli_outputs = list(cli_outputs)
        self.artifact_dir = tmp_path / "artifact"
        self.artifact_dir.mkdir(exist_ok=True)
        self.run = {"run_id": "run-1", "worktree": str(tmp_path / "worktree"),
                    "branch": "agent/aio-24", "artifact_dir": str(self.artifact_dir)}
        (tmp_path / "worktree").mkdir(exist_ok=True)

        class FakeSettings:
            @staticmethod
            def load(*, redacted: bool = True) -> dict:
                return {"agents": {"developer": _profile(provider), "qa": _profile("qodercli"),
                                   "planner": _profile("")},
                        "plane": {"api_key": ""}}

        board = web.TicketBoard.__new__(web.TicketBoard)
        board.catalog = _catalog(tmp_path)
        self.web, self.board, self.settings = web, board, FakeSettings()

    def build(self, monkeypatch: pytest.MonkeyPatch):
        from ticket_autopilot.engine import drivers
        from ticket_autopilot.services.run_manager import RunManager

        harness = self

        def fake_cli(agent, inputs, node, engine_root, **kwargs):
            harness.calls.append(agent)
            output = harness.cli_outputs.pop(0)
            if isinstance(output, Exception):
                raise output
            return output

        def fake_append_event(self, run, **kwargs):
            harness.events.append(kwargs)
            return kwargs

        monkeypatch.setattr(drivers, "cli_call", fake_cli)
        monkeypatch.setattr(RunManager, "__init__", lambda self, *args, **kwargs: None)
        monkeypatch.setattr(RunManager, "append_event", fake_append_event)
        loop = self.board._default_web_loop(settings=self.settings, repository=self.tmp_path)
        return loop.developer

    def event_types(self) -> list[str]:
        return [event["event_type"] for event in self.events]


def _developer_kwargs(harness: _LoopHarness) -> dict:
    return {"ticket_spec": {"issue_key": "AIO-24"}, "prompt": "do it", "run": harness.run,
            "findings": None, "role": "developer", "permission_mode": "write"}


def test_claude_developer_session_created_then_resumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _LoopHarness(tmp_path, "claude", ["done-1", "done-2"])
    developer = harness.build(monkeypatch)

    developer(**_developer_kwargs(harness))
    assert harness.event_types() == ["agent_session_started"]
    first_agent = harness.calls[0]
    session_id = first_agent["extra_args"][first_agent["extra_args"].index("--session-id") + 1]

    developer(**{**_developer_kwargs(harness), "findings": [{"id": "F1"}]})
    second_agent = harness.calls[1]
    assert second_agent["extra_args"][-2:] == ["-r", session_id]
    ledger = json.loads((harness.artifact_dir / LEDGER_FILENAME).read_text())
    assert ledger["sessions"]["developer"]["session_id"] == session_id


def test_codex_developer_parses_thread_id_and_resumes_exact_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_output = json.dumps({"type": "thread.started", "thread_id": "0198-codex-thread"}) + "\nfinal answer"
    harness = _LoopHarness(tmp_path, "codex", [first_output, "done-2"])
    developer = harness.build(monkeypatch)

    developer(**_developer_kwargs(harness))
    assert "--json" in harness.calls[0]["argv"]
    assert harness.event_types() == ["agent_session_started"]

    developer(**_developer_kwargs(harness))
    assert harness.calls[1]["argv"][:4] == ["codex", "exec", "resume", "0198-codex-thread"]


def test_codex_session_id_parse_failure_degrades_with_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _LoopHarness(tmp_path, "codex", ["no json here", "done-2"])
    developer = harness.build(monkeypatch)

    developer(**_developer_kwargs(harness))
    assert harness.event_types() == ["session_resume_unavailable"]

    developer(**_developer_kwargs(harness))
    assert "--ephemeral" in harness.calls[1]["argv"]
    assert "resume" not in harness.calls[1]["argv"]


def test_resume_failure_retries_fresh_once_with_recorded_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _LoopHarness(tmp_path, "claude", [
        "done-1", RuntimeError("cli driver (claude) exited 1: resume failed"), "fresh-done",
    ])
    developer = harness.build(monkeypatch)

    developer(**_developer_kwargs(harness))
    result = developer(**{**_developer_kwargs(harness), "findings": [{"id": "F1"}]})

    assert result == "fresh-done"
    assert harness.event_types() == ["agent_session_started", "session_resume_failed"]
    assert harness.calls[2]["extra_args"][-1] == "--no-session-persistence"
    ledger = json.loads((harness.artifact_dir / LEDGER_FILENAME).read_text())
    assert ledger["sessions"]["developer"]["session_id"] is None

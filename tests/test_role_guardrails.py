"""AIO-11 evidence: role checks reject before an Agent CLI process is spawned."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from ticket_autopilot.engine import drivers
from ticket_autopilot.engine.engine import Engine
from ticket_autopilot.engine.guardrails import GuardrailPolicy, SecurityError
from ticket_autopilot.services.run_manager import RunManager
from tests.test_run_worktree import ticket_spec


@pytest.fixture
def disposable_run(tmp_path: Path):
    import subprocess

    def git(*args, cwd=tmp_path):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Ticket Autopilot tests")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "initial")
    manager = RunManager(tmp_path)
    record = manager.create_run(ticket_spec())
    return manager, record


def developer_agent(record, **overrides):
    agent = {
        "role": "developer",
        "driver": "cli",
        "command": "agent-cli",
        "cwd": record.worktree,
        "branch": record.branch,
        "permission_mode": "write",
        "tools": ["Read", "Edit", "Write", "Bash"],
    }
    agent.update(overrides)
    return agent


def test_developer_write_is_allowed_only_in_its_exact_disposable_worktree(disposable_run):
    manager, record = disposable_run
    with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as spawn:
        spawn.return_value = mock.Mock(returncode=0, stdout="done", stderr="")
        result = drivers.cli_call(
            developer_agent(record), {}, {"agent": "developer"},
            str(manager.repository), policy=manager.developer_policy(record),
            run_context=record.execution_context(),
        )

    assert result == "done"
    assert spawn.call_count == 1
    assert spawn.call_args.kwargs["cwd"] == record.worktree


def test_engine_only_derives_writable_policy_from_an_explicit_run_context(disposable_run):
    manager, record = disposable_run
    workflow = {
        "agents": {"developer": developer_agent(record)},
        "nodes": [{"id": "develop", "agent": "developer"}],
        "edges": [],
    }
    with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as spawn:
        spawn.return_value = mock.Mock(returncode=0, stdout="done", stderr="")
        result = Engine(
            workflow, run_context=record, developer_policy=manager.developer_policy(record)
        ).run()

    assert result["outputs"]["develop"] == "done"
    assert spawn.call_count == 1


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"cwd": "/tmp"}, "outside allowed roots"),
        ({"branch": "main"}, "other than its Run branch"),
        ({"tools": ["Read", "Edit", "Write", "Bash", "Admin"]}, "tool whitelist"),
    ],
)
def test_developer_escape_main_and_privileged_tool_are_denied_before_spawn(disposable_run, overrides, error):
    manager, record = disposable_run
    with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as spawn:
        with pytest.raises(SecurityError, match=error):
            drivers.cli_call(
                developer_agent(record, **overrides), {}, {"agent": "developer"},
                str(manager.repository), policy=manager.developer_policy(record),
                run_context=record.execution_context(),
            )
    spawn.assert_not_called()


@pytest.mark.parametrize("role", ["planner", "qa"])
@pytest.mark.parametrize("tool", ["Write", "Edit", "Bash"])
def test_planner_and_qa_cannot_gain_mutating_tools_even_if_generic_policy_is_broadened(role, tool, disposable_run):
    manager, record = disposable_run
    agent = {
        "role": role,
        "command": "agent-cli",
        "cwd": record.worktree,
        "permission_mode": "read-only",
        "tools": ["Read", tool],
    }
    permissive_generic_policy = GuardrailPolicy(
        allowed_roots=[record.worktree], read_only=False,
        tool_whitelist=["Read", "Write", "Edit", "Bash"],
    )
    with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as spawn:
        with pytest.raises(SecurityError, match="cannot request mutating tools"):
            drivers.cli_call(
                agent, {}, {"agent": role}, str(manager.repository),
                policy=permissive_generic_policy, run_context=record.execution_context(),
            )
    spawn.assert_not_called()


@pytest.mark.parametrize("role", ["planner", "qa"])
def test_planner_and_qa_write_permission_is_denied_before_spawn(role, disposable_run):
    manager, record = disposable_run
    agent = {
        "role": role, "command": "agent-cli", "cwd": record.worktree,
        "permission_mode": "write", "tools": ["Read"],
    }
    policy = GuardrailPolicy(
        allowed_roots=[record.worktree], read_only=False, tool_whitelist=["Read"],
    )
    with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as spawn:
        with pytest.raises(SecurityError, match="read-only"):
            drivers.cli_call(agent, {}, {"agent": role}, str(manager.repository), policy=policy)
    spawn.assert_not_called()

"""AIO-23 Planner adapter tests: profile-driven read-only calls, classified errors.

The CLI is always faked; assertions cover the agent shape handed to
``drivers.cli_call`` and each stable failure classification code.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ticket_autopilot.services.agent_catalog import AgentCatalog
from ticket_autopilot.services.planner_adapter import (
    PLANNER_CLI_FAILED,
    PLANNER_CLI_UNAVAILABLE,
    PLANNER_OUTPUT_INVALID,
    PLANNER_UNCONFIGURED,
    PLANNER_SYSTEM,
    PlannerAdapterError,
    build_planner,
)

CONTEXT = {"issue_key": "AIO-23", "repository": "/tmp/repo"}


class FakeSettings:
    def __init__(self, planner_profile: dict[str, str] | None):
        self.planner_profile = planner_profile

    def load(self, *, redacted: bool = True) -> dict:
        return {"agents": {"planner": self.planner_profile}}


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


def test_claude_planner_builds_read_only_call_and_returns_prompts(tmp_path: Path) -> None:
    calls: list[tuple[dict, dict]] = []

    def fake_cli(agent, inputs, node, engine_root, **_kwargs):
        calls.append((agent, inputs))
        return json.dumps({"dev": "立即执行 dev prompt", "acceptance": "立即执行 acceptance prompt"})

    planner = build_planner(FakeSettings({"provider": "claude", "model": "", "reasoning": "high"}),
                            tmp_path, _catalog(tmp_path), cli_call=fake_cli)
    result = planner(context=CONTEXT, missing_roles=("dev", "acceptance"))

    assert result == {"dev": "立即执行 dev prompt", "acceptance": "立即执行 acceptance prompt"}
    agent, inputs = calls[0]
    assert agent["command"] == "claude"
    assert agent["permission_mode"] == "read-only"
    assert agent["tools"] == ["Read", "Glob", "Grep"]
    assert agent["cwd"] == str(tmp_path.resolve())
    assert "--no-session-persistence" in agent["extra_args"]
    assert "Controller-supplied deterministic command evidence" in agent["system"]
    assert "rerunning pytest" in agent["system"]
    assert inputs["requested_roles"] == "dev, acceptance"
    assert json.loads(inputs["context"]) == CONTEXT


def test_codex_planner_reads_last_message_file_instead_of_stdout(tmp_path: Path) -> None:
    def fake_cli(agent, inputs, node, engine_root, **_kwargs):
        argv = agent["argv"]
        assert argv[:4] == ["codex", "exec", "-s", "read-only"]
        assert argv[-1] == "{prompt}"
        output_path = argv[argv.index("-o") + 1]
        Path(output_path).write_text(json.dumps({"dev": "立即执行 via file"}), encoding="utf-8")
        return "codex progress noise\nnot json"

    planner = build_planner(FakeSettings({"provider": "codex", "model": "", "reasoning": ""}),
                            tmp_path, _catalog(tmp_path), cli_call=fake_cli)
    assert planner(context=CONTEXT, missing_roles=("dev",)) == {"dev": "立即执行 via file"}


def test_error_classification_codes(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    with pytest.raises(PlannerAdapterError) as unconfigured:
        build_planner(FakeSettings({"provider": "", "model": "", "reasoning": ""}), tmp_path, catalog,
                      cli_call=lambda *args, **kwargs: "{}")(context=CONTEXT, missing_roles=("dev",))
    assert unconfigured.value.code == PLANNER_UNCONFIGURED

    unavailable_catalog = AgentCatalog(runner=lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1, "", ""),
                                       which=lambda _command: None, codex_config_path=tmp_path / "missing.toml")
    with pytest.raises(PlannerAdapterError) as unavailable:
        build_planner(FakeSettings({"provider": "claude", "model": "", "reasoning": ""}), tmp_path,
                      unavailable_catalog, cli_call=lambda *args, **kwargs: "{}")(context=CONTEXT, missing_roles=("dev",))
    assert unavailable.value.code == PLANNER_CLI_UNAVAILABLE
    assert unavailable.value.profile["provider"] == "claude"

    def failing_cli(*_args, **_kwargs):
        raise RuntimeError("cli driver (claude) exited 1: boom")

    with pytest.raises(PlannerAdapterError) as failed:
        build_planner(FakeSettings({"provider": "claude", "model": "", "reasoning": ""}), tmp_path, catalog,
                      cli_call=failing_cli)(context=CONTEXT, missing_roles=("dev",))
    assert failed.value.code == PLANNER_CLI_FAILED

    for bad_output in ("not json at all", json.dumps(["list"]), json.dumps({"acceptance": "x"})):
        with pytest.raises(PlannerAdapterError) as invalid:
            build_planner(FakeSettings({"provider": "claude", "model": "", "reasoning": ""}), tmp_path, catalog,
                          cli_call=lambda *args, _output=bad_output, **kwargs: _output)(context=CONTEXT, missing_roles=("dev",))
        assert invalid.value.code == PLANNER_OUTPUT_INVALID


def test_hard_break_metadata_records_code_and_profile(tmp_path: Path) -> None:
    from ticket_autopilot.services.prompt_resolver import PromptResolver

    (tmp_path / "tasks").mkdir()
    resolver = PromptResolver(tmp_path)
    planner = build_planner(FakeSettings({"provider": "", "model": "", "reasoning": ""}),
                            tmp_path, _catalog(tmp_path), cli_call=lambda *args, **kwargs: "{}")
    result = resolver.prepare(issue_key="AIO-23", ticket_spec={"repository": str(tmp_path)},
                              source_issue={"identifier": "AIO-23"}, planner=planner)

    assert result["status"] == "HARD_BREAK_PLANNER"
    assert result["planner_error_code"] == PLANNER_UNCONFIGURED
    assert result["planner_profile"] == {"provider": "", "model": "", "reasoning": ""}
    metadata = json.loads((tmp_path / result["artifact_dir"] / "prompt-metadata.json").read_text())
    assert metadata["planner_error_code"] == PLANNER_UNCONFIGURED

"""AIO-22 agent catalog tests: probing, TTL cache, validation, call building.

All probes are faked (runner/which/codex config path); no real CLI is spawned.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ticket_autopilot.services.agent_catalog import (
    AgentCatalog,
    CatalogError,
    empty_profile,
    normalize_profile,
)

_CLAUDE_HELP = """Usage: claude [options]
  --model <model>    Model for the current session
  --effort <effort>  Override the default reasoning effort level (low, medium,
                     high, xhigh, max)
  --permission-mode <mode>              Permission mode to use for the session
                                        (choices: "acceptEdits", "auto",
                                        "bypassPermissions", "manual",
                                        "dontAsk", "plan")
"""

_QODERCLI_HELP = """Usage: qodercli [options]
  --permission-mode <mode>             Set the permission mode (choices:
                                       default, accept_edits,
                                       bypass_permissions, dont_ask, auto)
"""

_CODEX_HELP = """Usage: codex [OPTIONS]
  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated
          shell commands

          [possible values: read-only, workspace-write, danger-full-access]
"""


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]):
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        returncode, stdout = self.responses.get(tuple(cmd), (1, ""))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _full_catalog(tmp_path: Path, *, clock: FakeClock | None = None) -> tuple[AgentCatalog, FakeRunner]:
    codex_config = tmp_path / "config.toml"
    codex_config.write_text('model = "gpt-5.6-terra"\nmodel_reasoning_effort = "xhigh"\n')
    runner = FakeRunner({
        ("codex", "--version"): (0, "codex-cli 0.145.0\n"),
        ("codex", "--help"): (0, _CODEX_HELP),
        ("claude", "--version"): (0, "2.1.220 (Claude Code)\n"),
        ("claude", "--help"): (0, _CLAUDE_HELP),
        ("qodercli", "--version"): (0, "1.1.9 (Qoder CLI)\n"),
        ("qodercli", "--help"): (0, _QODERCLI_HELP),
        ("qodercli", "--list-models"): (0, "MODEL\nUltimate\n"),
    })
    catalog = AgentCatalog(
        runner=runner, which=lambda command: f"/usr/local/bin/{command}",
        codex_config_path=codex_config, clock=clock or FakeClock(),
    )
    return catalog, runner


def test_probe_discovers_options_per_provider_without_hardcoded_models(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)
    providers = catalog.snapshot()["providers"]

    assert providers["codex"] == {
        "label": "Codex CLI", "command": "codex", "available": True, "reason": "",
        "version": "codex-cli 0.145.0", "models": ["gpt-5.6-terra"], "reasoning": ["xhigh"],
        "permission_modes": ["read-only", "workspace-write", "danger-full-access"],
    }
    assert providers["claude"]["available"] is True
    assert providers["claude"]["models"] == []
    assert providers["claude"]["reasoning"] == ["low", "medium", "high", "xhigh", "max"]
    assert providers["claude"]["permission_modes"] == [
        "acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan",
    ]
    assert providers["qodercli"]["available"] is True
    assert providers["qodercli"]["models"] == ["Ultimate"]
    assert providers["qodercli"]["reasoning"] == []
    assert providers["qodercli"]["permission_modes"] == [
        "default", "accept_edits", "bypass_permissions", "dont_ask", "auto",
    ]


def test_probe_failures_degrade_to_unavailable_with_reason(tmp_path: Path) -> None:
    def crashing_runner(cmd, **_kwargs):
        if cmd[0] == "claude":
            raise OSError("boom")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    catalog = AgentCatalog(
        runner=crashing_runner,
        which=lambda command: None if command == "codex" else f"/bin/{command}",
        codex_config_path=tmp_path / "missing.toml",
    )
    providers = catalog.snapshot()["providers"]
    assert providers["codex"] == {
        "label": "Codex CLI", "command": "codex", "available": False,
        "reason": "codex is not on PATH", "version": "", "models": [], "reasoning": [],
        "permission_modes": [],
    }
    for name in ("claude", "qodercli"):
        assert providers[name]["available"] is False
        assert providers[name]["reason"]


def test_snapshot_uses_ttl_cache_and_refresh_reprobes(tmp_path: Path) -> None:
    clock = FakeClock()
    catalog, runner = _full_catalog(tmp_path, clock=clock)
    catalog.snapshot()
    probed_once = len(runner.calls)

    catalog.snapshot()
    assert len(runner.calls) == probed_once  # cache hit inside TTL

    catalog.snapshot(refresh=True)
    assert len(runner.calls) == probed_once * 2

    clock.now += 301.0
    catalog.snapshot()
    assert len(runner.calls) == probed_once * 3


def test_validate_profile_gates_values_against_probed_catalog(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)

    assert catalog.validate_profile("planner", empty_profile()) == empty_profile()
    assert catalog.validate_profile("developer", {"provider": "codex", "model": "gpt-5.6-terra", "reasoning": "xhigh"}) == {
        "provider": "codex", "model": "gpt-5.6-terra", "reasoning": "xhigh", "permission_mode": "",
    }

    with pytest.raises(CatalogError, match="unknown agent role"):
        catalog.validate_profile("owner", empty_profile())
    with pytest.raises(CatalogError, match="must be an object"):
        catalog.validate_profile("qa", "codex")
    with pytest.raises(CatalogError, match="unsupported fields"):
        catalog.validate_profile("qa", {"provider": "codex", "argv": ["rm"]})
    with pytest.raises(CatalogError, match="require a provider"):
        catalog.validate_profile("qa", {"provider": "", "model": "Ultimate", "reasoning": ""})
    with pytest.raises(CatalogError, match="must be one of"):
        catalog.validate_profile("qa", {"provider": "gemini", "model": "", "reasoning": ""})
    with pytest.raises(CatalogError, match="not in the probed catalog"):
        catalog.validate_profile("qa", {"provider": "qodercli", "model": "made-up", "reasoning": ""})
    with pytest.raises(CatalogError, match="not in the probed catalog"):
        catalog.validate_profile("qa", {"provider": "claude", "model": "", "reasoning": "extreme"})
    with pytest.raises(CatalogError, match="unsupported characters"):
        catalog.validate_profile("qa", {"provider": "claude", "model": "", "reasoning": "high --dangerously-skip"})


def test_validate_profile_gates_permission_modes_by_role(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)

    # A probed writable mode is fine for the Developer.
    checked = catalog.validate_profile("developer", {"provider": "qodercli", "permission_mode": "accept_edits"})
    assert checked["permission_mode"] == "accept_edits"
    # Read-only roles may only pick non-mutating modes.
    assert catalog.validate_profile("qa", {"provider": "qodercli", "permission_mode": "default"})["permission_mode"] == "default"
    assert catalog.validate_profile("planner", {"provider": "claude", "permission_mode": "plan"})["permission_mode"] == "plan"

    with pytest.raises(CatalogError, match="not in the probed catalog"):
        catalog.validate_profile("developer", {"provider": "qodercli", "permission_mode": "acceptEdits"})
    for role, provider, mode in (("qa", "qodercli", "bypass_permissions"), ("planner", "claude", "acceptEdits"),
                                 ("qa", "codex", "workspace-write")):
        with pytest.raises(CatalogError, match="read-only role"):
            catalog.validate_profile(role, {"provider": provider, "permission_mode": mode})


def test_validate_profile_rejects_configured_but_unavailable_provider(tmp_path: Path) -> None:
    catalog = AgentCatalog(runner=FakeRunner({}), which=lambda _command: None,
                           codex_config_path=tmp_path / "missing.toml")
    with pytest.raises(CatalogError, match="unavailable"):
        catalog.validate_profile("developer", {"provider": "codex", "model": "", "reasoning": ""})
    # An empty profile stays saveable even when nothing is installed.
    assert catalog.validate_profile("developer", empty_profile()) == empty_profile()


def test_build_agent_codex_argv_shapes(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)
    developer = catalog.build_agent(
        {"provider": "codex", "model": "gpt-5.6-terra", "reasoning": "xhigh"},
        role="developer", cwd="/tmp/worktree", allowed_roots=["/tmp/worktree"], system="Do the work.",
    )
    assert developer["driver"] == "cli"
    assert developer["permission_mode"] == "write"
    assert developer["read_only"] is False
    assert developer["tools"] == ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]
    assert developer["argv"] == [
        "codex", "exec", "-s", "workspace-write", "-C", "{cwd}",
        "--skip-git-repo-check", "--color", "never",
        "-m", "gpt-5.6-terra", "-c", 'model_reasoning_effort="xhigh"', "{prompt}",
    ]

    qa = catalog.build_agent({"provider": "codex", "model": "", "reasoning": ""},
                             role="qa", cwd="sandbox", allowed_roots=["sandbox"], expect="json")
    assert qa["permission_mode"] == "read-only"
    assert qa["expect"] == "json"
    assert qa["argv"] == [
        "codex", "exec", "-s", "read-only", "-C", "{cwd}",
        "--skip-git-repo-check", "--color", "never", "--ephemeral", "{prompt}",
    ]


def test_build_agent_claude_and_qodercli_flag_shapes(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)

    planner = catalog.build_agent({"provider": "claude", "model": "", "reasoning": "high"},
                                  role="planner", cwd="sandbox", allowed_roots=["sandbox"], system="Plan.")
    assert planner["command"] == "claude"
    assert "argv" not in planner
    assert planner["tools"] == ["Read", "Glob", "Grep"]
    assert planner["extra_args"] == ["--effort", "high", "--no-session-persistence"]

    qa = catalog.build_agent({"provider": "qodercli", "model": "Ultimate", "reasoning": ""},
                             role="qa", cwd="sandbox", allowed_roots=["sandbox"], expect="json")
    assert qa["command"] == "qodercli"
    assert qa["tools_flag"] == "--tools"
    assert qa["tools_as_args"] is True
    assert qa["extra_args"] == ["-m", "Ultimate", "--allowed-tools", "Read,Glob,Grep", "--no-session-persistence"]

    developer = catalog.build_agent({"provider": "qodercli", "model": "", "reasoning": ""},
                                    role="developer", cwd="/w", allowed_roots=["/w"])
    assert developer["permission_mode"] == "write"
    assert "--no-session-persistence" not in developer.get("extra_args", [])
    assert "--allowed-tools" not in developer.get("extra_args", [])


def test_build_agent_applies_explicit_permission_mode_choice(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)

    codex = catalog.build_agent({"provider": "codex", "permission_mode": "danger-full-access"},
                                role="developer", cwd="/w", allowed_roots=["/w"])
    assert codex["argv"][2:4] == ["-s", "danger-full-access"]

    qodercli = catalog.build_agent({"provider": "qodercli", "permission_mode": "dont_ask"},
                                   role="developer", cwd="/w", allowed_roots=["/w"])
    assert qodercli["cli_permission_mode"] == "dont_ask"
    # The internal guardrail vocabulary is untouched by the CLI-level choice.
    assert qodercli["permission_mode"] == "write"

    planner = catalog.build_agent({"provider": "claude", "permission_mode": "plan"},
                                  role="planner", cwd="sandbox", allowed_roots=["sandbox"])
    assert planner["cli_permission_mode"] == "plan"
    default = catalog.build_agent({"provider": "claude", "model": "", "reasoning": ""},
                                  role="planner", cwd="sandbox", allowed_roots=["sandbox"])
    assert "cli_permission_mode" not in default


def test_build_agent_requires_a_configured_provider(tmp_path: Path) -> None:
    catalog, _runner = _full_catalog(tmp_path)
    with pytest.raises(CatalogError, match="no provider configured"):
        catalog.build_agent(empty_profile(), role="qa", cwd="sandbox", allowed_roots=["sandbox"])


def test_normalize_profile_migrates_legacy_strings_safely() -> None:
    assert normalize_profile("codex") == {**empty_profile(), "provider": "codex"}
    assert normalize_profile(" claude ") == {**empty_profile(), "provider": "claude"}
    # Arbitrary saved strings must never be reinterpreted as a command.
    assert normalize_profile("rm -rf /") == empty_profile()
    assert normalize_profile(None) == empty_profile()
    assert normalize_profile({"provider": "qodercli", "model": "Ultimate", "junk": "x"}) == {
        **empty_profile(), "provider": "qodercli", "model": "Ultimate",
    }
    assert normalize_profile({"provider": 7}) == empty_profile()

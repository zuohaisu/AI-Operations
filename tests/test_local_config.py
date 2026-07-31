"""AIO-17 private local settings tests; no real user HOME is used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from ticket_autopilot.services.agent_catalog import empty_profile
from ticket_autopilot.web import LocalConfig, MASK, atomic_json_write, redact_secrets


def test_config_round_trip_masks_api_key_and_is_private(tmp_path: Path) -> None:
    state = tmp_path / ".ticket-autopilot"
    config = LocalConfig(state)
    saved = config.save({
        "plane": {"workspace": "hspace", "project": "aio", "api_key": "plane-secret-value"},
        "repository": "/tmp/repository",
        "agents": {"planner": {"provider": "codex", "model": "", "reasoning": ""},
                   "developer": {"provider": "claude", "model": "", "reasoning": "high"},
                   "qa": {"provider": "qodercli", "model": "Ultimate", "reasoning": ""}},
    })

    assert saved["plane"]["api_key"] == MASK
    assert config.load()["plane"]["api_key"] == MASK
    assert config.load(redacted=False)["plane"]["api_key"] == "plane-secret-value"
    assert config.load()["agents"] == {
        "planner": {**empty_profile(), "provider": "codex"},
        "developer": {**empty_profile(), "provider": "claude", "reasoning": "high"},
        "qa": {**empty_profile(), "provider": "qodercli", "model": "Ultimate"},
    }
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "config.json").stat().st_mode) == 0o600


def test_legacy_string_agents_migrate_to_profiles_without_losing_config(tmp_path: Path) -> None:
    state = tmp_path / ".ticket-autopilot"
    atomic_json_write(state / "config.json", {
        "plane": {"workspace": "hspace", "project": "aio", "api_key": "keep-me"},
        "repository": "/tmp/repository",
        "agents": {"planner": "codex", "developer": "claude", "qa": "qodercli --tools read"},
    })
    config = LocalConfig(state)

    loaded = config.load(redacted=False)
    assert loaded["plane"]["api_key"] == "keep-me"
    assert loaded["repository"] == "/tmp/repository"
    assert loaded["agents"]["planner"] == {**empty_profile(), "provider": "codex"}
    assert loaded["agents"]["developer"] == {**empty_profile(), "provider": "claude"}
    # Arbitrary legacy command strings are dropped, never re-run.
    assert loaded["agents"]["qa"] == empty_profile()

    # Saving an unrelated field keeps the migrated shape on disk.
    saved = config.save({"repository": "/tmp/other"})
    assert saved["agents"]["planner"] == {**empty_profile(), "provider": "codex"}
    assert json.loads((state / "config.json").read_text())["agents"]["developer"]["provider"] == "claude"


def test_agent_profile_validator_gates_only_submitted_roles(tmp_path: Path) -> None:
    def validator(role: str, profile: dict) -> dict:
        if profile.get("provider") == "codex":
            raise ValueError(f"agents.{role}.provider codex is unavailable")
        return profile

    config = LocalConfig(tmp_path / ".ticket-autopilot", agent_profile_validator=validator)
    with pytest.raises(ValueError, match="unavailable"):
        config.save({"agents": {"qa": {"provider": "codex", "model": "", "reasoning": ""}}})
    assert config.load()["agents"]["qa"] == empty_profile()

    saved = config.save({"agents": {"qa": {"provider": "qodercli", "model": "", "reasoning": ""}}})
    assert saved["agents"]["qa"]["provider"] == "qodercli"
    # A plane-only save must not re-validate untouched roles.
    saved = config.save({"plane": {"workspace": "hspace"}})
    assert saved["plane"]["workspace"] == "hspace"


def test_atomic_write_keeps_previous_json_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    atomic_json_write(target, {"version": "before"})

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_json_write(target, {"version": "after"})
    assert json.loads(target.read_text()) == {"version": "before"}
    assert not list(tmp_path.glob(".config.json.*.tmp"))


def test_recursive_secret_redaction_never_echoes_values() -> None:
    value = {"token": "top-secret", "nested": [{"api_key": "also-secret"}], "normal": "safe"}
    assert redact_secrets(value) == {"token": MASK, "nested": [{"api_key": MASK}], "normal": "safe"}

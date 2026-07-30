"""AIO-17 private local settings tests; no real user HOME is used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from ticket_autopilot.web import LocalConfig, MASK, atomic_json_write, redact_secrets


def test_config_round_trip_masks_api_key_and_is_private(tmp_path: Path) -> None:
    state = tmp_path / ".ticket-autopilot"
    config = LocalConfig(state)
    saved = config.save({
        "plane": {"workspace": "hspace", "project": "aio", "api_key": "plane-secret-value"},
        "repository": "/tmp/repository",
        "agents": {"planner": "codex", "developer": "claude", "qa": "qodercli"},
    })

    assert saved["plane"]["api_key"] == MASK
    assert config.load()["plane"]["api_key"] == MASK
    assert config.load(redacted=False)["plane"]["api_key"] == "plane-secret-value"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "config.json").stat().st_mode) == 0o600


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

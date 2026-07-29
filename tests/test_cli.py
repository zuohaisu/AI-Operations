"""AIO-14 product CLI contract tests; no Plane, GitHub, or Agent process is used."""

from __future__ import annotations

import errno
from pathlib import Path
from unittest import mock

import pytest

from ticket_autopilot import cli
from ticket_autopilot.services.ticket_controller import ControllerError, TicketController


def test_help_lists_only_supported_product_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for command in ("run", "status", "cancel", "cleanup"):
        assert command in help_text
    assert "resume" not in help_text


@pytest.mark.parametrize("status, expected", [
    ("IN_REVIEW", 0), ("CLEANED", 0), ("ACTIVE", 2), ("BLOCKED_REQUIREMENTS", 2),
    ("CANCELLED", 2), ("STALLED", 2),
])
def test_exit_code_contract_never_treats_incomplete_states_as_success(status, expected):
    assert cli._exit_code({"status": status}) == expected


def test_missing_plane_credential_fails_before_plane_read_or_agent(tmp_path: Path):
    # A non-repository is rejected first, so make a tiny isolated Git repository.
    import subprocess
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    (tmp_path / "README").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True, capture_output=True)
    controller = TicketController(tmp_path, environ={})
    with mock.patch("ticket_autopilot.services.ticket_controller.plane.fetch_issue_by_identifier") as fetch:
        with pytest.raises(ControllerError, match="PLANE_API_KEY") as exc:
            controller.run("AIO-14")
    assert exc.value.code == "CREDENTIAL_REQUIRED"
    fetch.assert_not_called()


def test_process_group_leader_retries_isolation_in_a_child():
    leader_error = OSError(errno.EPERM, "operation not permitted")
    with mock.patch.object(cli.os, "setsid", side_effect=[leader_error, None]) as setsid:
        with mock.patch.object(cli.os, "fork", return_value=0) as fork:
            assert cli._isolate_run_process_group() is None
    assert setsid.call_count == 2
    fork.assert_called_once_with()


def test_cli_prints_actionable_preflight_error_without_secret(monkeypatch, capsys):
    class MissingCredential:
        def __init__(self, *_args):
            from ticket_autopilot.services.ticket_controller import ControllerError
            raise ControllerError("CREDENTIAL_REQUIRED", "set PLANE_API_KEY in the environment")

    monkeypatch.setattr(cli, "TicketController", MissingCredential)
    assert cli.main(["run", "AIO-14"]) == cli.EXIT_PREFLIGHT
    error = capsys.readouterr().err
    assert "CREDENTIAL_REQUIRED" in error
    assert "PLANE_API_KEY" in error
    assert "secret" not in error.casefold()

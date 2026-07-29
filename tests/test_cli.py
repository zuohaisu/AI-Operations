"""AIO-14 product CLI contract tests; no Plane, GitHub, or Agent process is used."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import subprocess
import sys
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


def test_group_leader_subprocess_relays_preflight_exit_once(tmp_path: Path):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    (tmp_path / "README").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True, capture_output=True)
    environment = dict(os.environ, AIO14_TEST_REPOSITORY=str(tmp_path))
    environment.pop("PLANE_API_KEY", None)
    probe = (
        "import os; from ticket_autopilot import cli; os.setpgid(0, 0); "
        "raise SystemExit(cli.main(['--repository', os.environ['AIO14_TEST_REPOSITORY'], 'run', 'AIO-14']))"
    )
    result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True, env=environment)
    assert result.returncode == cli.EXIT_PREFLIGHT
    assert result.stderr.count("CREDENTIAL_REQUIRED") == 1


def test_process_group_leader_hard_exits_forked_child_after_dispatch():
    leader_error = OSError(errno.EPERM, "operation not permitted")
    with mock.patch.object(cli.os, "setsid", side_effect=[leader_error, None]) as setsid:
        with mock.patch.object(cli.os, "fork", return_value=0) as fork:
            with mock.patch.object(cli.os, "_exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))) as hard_exit:
                with pytest.raises(SystemExit) as exc:
                    cli._run_in_isolated_process(lambda: cli.EXIT_PREFLIGHT)
    assert exc.value.code == cli.EXIT_PREFLIGHT
    assert setsid.call_count == 2
    fork.assert_called_once_with()
    hard_exit.assert_called_once_with(cli.EXIT_PREFLIGHT)


def test_dispatch_prints_actionable_preflight_error_without_secret(monkeypatch, capsys):
    """Unit-test formatting below the fork boundary; subprocess tests cover CLI I/O."""
    class MissingCredential:
        def __init__(self, *_args):
            raise ControllerError("CREDENTIAL_REQUIRED", "set PLANE_API_KEY in the environment")

    monkeypatch.setattr(cli, "TicketController", MissingCredential)
    args = cli.build_parser().parse_args(["run", "AIO-14"])
    assert cli._dispatch(args) == cli.EXIT_PREFLIGHT
    error = capsys.readouterr().err
    assert "CREDENTIAL_REQUIRED" in error
    assert "PLANE_API_KEY" in error
    assert "secret" not in error.casefold()

"""Command-line interface for one disposable Ticket Autopilot Run.

Subcommands:
  run <ISSUE_KEY>     start the AIO-13 ticket workflow
  status <ISSUE_KEY>  show an owned Run's retained state
  cancel <ISSUE_KEY>  terminate an owned active Run
  cleanup <ISSUE_KEY> remove only confirmed disposable local resources
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
from typing import Any, Callable

from ticket_autopilot.services.ticket_controller import (
    ControllerError,
    SUCCESS_STATUSES,
    TicketController,
)

EXIT_SUCCESS = 0
EXIT_NON_SUCCESS_STATE = 2
EXIT_PREFLIGHT = 3
EXIT_SAFE_REFUSAL = 4
EXIT_RUNTIME_ERROR = 5

_PREFLIGHT_CODES = {
    "REPOSITORY_REQUIRED", "REPOSITORY_INVALID", "CREDENTIAL_REQUIRED",
    "AGENT_CLI_REQUIRED", "ISSUE_KEY_INVALID", "ISSUE_KEY_MISMATCH",
    "PLANE_READ_FAILED",
}
_SAFE_REFUSAL_CODES = {"RUN_NOT_FOUND", "RUN_OWNERSHIP_MISMATCH", "RUN_AMBIGUOUS"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ticket-controller", description=__doc__)
    parser.add_argument("--repository", help="local Git repository (defaults to TICKET_AUTOPILOT_REPOSITORY)")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("run", "start a disposable ticket run"),
        ("status", "show current owned run status"),
        ("cancel", "safely stop an owned active run"),
        ("cleanup", "remove confirmed local disposable resources"),
    ):
        child = sub.add_parser(command, help=help_text)
        child.add_argument("issue_key")
        if command != "run":
            child.add_argument("--run-id", help="select an exact owned Run when needed")
    return parser


def _exit_code(result: dict[str, Any]) -> int:
    status = str(result.get("status", "STALLED"))
    if status in SUCCESS_STATUSES:
        return EXIT_SUCCESS
    # ACTIVE, CANCELLED, STALLED, all BLOCKED states, and incomplete preflight
    # outcomes are intentionally observable failures, never false success.
    return EXIT_NON_SUCCESS_STATE


def _print(value: dict[str, Any], *, stream=None) -> None:
    print(json.dumps(value, sort_keys=True, default=str), file=stream or sys.stdout)


def _run_in_isolated_process(run: Callable[[], int]) -> int:
    """Execute ``run`` in a process group cancel can safely terminate.

    ``setsid`` rejects a process-group leader.  In that case a fork child can
    create the session.  Crucially the child calls :func:`os._exit` after the
    callback: returning would resume an embedding caller's stack (for example
    pytest) and could make the parent relay an unrelated successful exit code.
    """
    if os.name != "posix":
        raise ControllerError("RUN_ISOLATION_FAILED", "safe Run cancellation requires a POSIX process group")
    try:
        os.setsid()
    except OSError as exc:
        if exc.errno != errno.EPERM:
            raise ControllerError("RUN_ISOLATION_FAILED", f"could not isolate Run process group: {exc}") from exc
        try:
            child_pid = os.fork()
        except OSError as fork_error:
            raise ControllerError("RUN_ISOLATION_FAILED", f"could not create isolated Run process: {fork_error}") from fork_error
        if child_pid:
            _, wait_status = os.waitpid(child_pid, 0)
            return os.waitstatus_to_exitcode(wait_status)
        try:
            os.setsid()
        except OSError as child_error:  # Defensive: a fork child is not a group leader.
            _print({"status": "ERROR", "code": "RUN_ISOLATION_FAILED", "error": f"could not isolate forked Run process: {child_error}"}, stream=sys.stderr)
            os._exit(EXIT_RUNTIME_ERROR)
        exit_code = run()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    return run()


def _dispatch(args: argparse.Namespace) -> int:
    try:
        controller = TicketController(args.repository)
        if args.command == "run":
            result = controller.run(args.issue_key)
        elif args.command == "status":
            result = controller.status(args.issue_key, run_id=args.run_id)
        elif args.command == "cancel":
            result = controller.cancel(args.issue_key, run_id=args.run_id)
        else:
            result = controller.cleanup(args.issue_key, run_id=args.run_id)
    except ControllerError as exc:
        _print({"status": "ERROR", "code": exc.code, "error": str(exc)}, stream=sys.stderr)
        if exc.code in _PREFLIGHT_CODES:
            return EXIT_PREFLIGHT
        if exc.code in _SAFE_REFUSAL_CODES:
            return EXIT_SAFE_REFUSAL
        return EXIT_RUNTIME_ERROR
    except Exception as exc:  # Do not leak environment variables or connector internals as success.
        _print({"status": "ERROR", "code": "UNEXPECTED", "error": str(exc)}, stream=sys.stderr)
        return EXIT_RUNTIME_ERROR
    _print(result)
    return _exit_code(result)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_in_isolated_process(lambda: _dispatch(args))
    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface for Ticket Autopilot.

Subcommands (spec §13):
  run <ISSUE_KEY>     start a disposable ticket run
  status <ISSUE_KEY>  show current run status
  cancel <ISSUE_KEY>  stop the run and mark it cancelled
  cleanup <ISSUE_KEY> remove worktree/branch, keep logs

Note: `resume` is intentionally NOT supported (spec §13.5).
"""

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ticket-controller", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="start a disposable ticket run").add_argument("issue_key")
    sub.add_parser("status", help="show current run status").add_argument("issue_key")
    sub.add_parser("cancel", help="stop the run").add_argument("issue_key")
    sub.add_parser("cleanup", help="remove worktree/branch").add_argument("issue_key")

    args = parser.parse_args(argv)
    # TODO(T1/T16): wire to controller. Stub returns 0 for now.
    print(f"[stub] command={args.command} issue={getattr(args, 'issue_key', None)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

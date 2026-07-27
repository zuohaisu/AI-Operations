#!/usr/bin/env python3
"""Ensure a target ticket exists. If TICKET_ID env is set, use it; otherwise
create a temporary test ticket and remember it (via .created) so cleanup can
remove it later. Prints the ticket id to stdout."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plane_client as pc

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    tid = os.environ.get("TICKET_ID", "").strip()
    created = False
    if not tid:
        iss = pc.create_issue(
            "[DAGU-POC] ticket-pipeline test ticket",
            state_key="todo",
            description_html="Auto-created by Dagu PoC to validate the ticket-pipeline workflow.",
        )
        tid = iss["id"]
        created = True
        print(f"created test ticket {tid}", file=sys.stderr)
    else:
        print(f"using provided ticket {tid}", file=sys.stderr)

    with open(os.path.join(HERE, ".tid"), "w") as f:
        f.write(tid)
    with open(os.path.join(HERE, ".created"), "w") as f:
        f.write(tid if created else "")

    print(tid)


if __name__ == "__main__":
    main()

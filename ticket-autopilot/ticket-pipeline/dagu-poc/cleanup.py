#!/usr/bin/env python3
"""Cleanup step. Only deletes the ticket if this run created it (recorded in
.created by ensure_ticket). Harmless no-op otherwise."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plane_client as pc

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    marker = os.path.join(HERE, ".created")
    if not os.path.exists(marker):
        print("no cleanup marker; nothing to delete")
        return
    tid = open(marker).read().strip()
    if not tid:
        print("ticket was user-provided; leaving it intact")
        return
    pc.delete_issue(tid)
    os.remove(marker)
    print(f"cleaned up test ticket {tid}")


if __name__ == "__main__":
    main()

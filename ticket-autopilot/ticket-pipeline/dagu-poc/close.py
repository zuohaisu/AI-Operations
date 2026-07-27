#!/usr/bin/env python3
"""Close step. Posts the plan + result as a comment and moves the ticket to
done via plane_client (already proven against the real Plane API)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plane_client as pc

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")


def main():
    tid = open(os.path.join(HERE, ".tid")).read().strip()
    plan = open(os.path.join(ART, "plan.md")).read()
    result = open(os.path.join(ART, "result.md")).read()
    comment = (
        "## Pipeline result\n\n"
        f"### Plan\n{plan}\n\n"
        f"### Execute result\n{result}\n"
    )
    pc.add_comment(tid, comment)
    pc.set_state(tid, "done")
    print(f"ticket {tid} closed (state=done, comment posted)")


if __name__ == "__main__":
    main()

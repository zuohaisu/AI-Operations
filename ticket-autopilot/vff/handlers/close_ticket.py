"""Closer handler — the only node that touches Plane in the real run.

Invoked by the `script` driver as `close_ticket(**inputs)`. Uses the existing
plane_client (shared with the ticket-pipeline orchestrator) to post the
plan+result as a comment and move the ticket to done.

In `--mock` mode this handler is never called (the workflow's `mock.closer`
returns a canned value instead).
"""

import os
import sys

# plane_client lives in ../ticket-pipeline (sibling of vivarium-forge-flow)
_TP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "ticket-pipeline"))
if _TP not in sys.path:
    sys.path.insert(0, _TP)

import plane_client as pc  # noqa: E402


def close_ticket(ticket_id: str, plan: str, result: str) -> dict:
    comment = f"## Plan\n{plan}\n\n## Execute result\n{result}\n"
    pc.add_comment(ticket_id, comment)
    pc.set_state(ticket_id, "done")
    return {"closed": True, "ticket_id": ticket_id}

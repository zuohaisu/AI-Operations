"""Closer handler — the Engine's single Plane side-effecting node.

The handler formats workflow evidence, then delegates all Plane I/O to the
parameterized connector.  In ``--mock`` mode the Engine returns its canned
closer value and this function is not called.
"""

from __future__ import annotations

from ticket_autopilot.connectors.plane import close_ticket as close_plane_ticket


def close_ticket(ticket_id: str, plan: object, result: object) -> dict:
    """Post plan/execution evidence and move the configured Plane ticket to Done."""
    summary = f"## Plan\n{plan}\n\n## Execute result\n{result}\n"
    return close_plane_ticket(ticket_id, summary)

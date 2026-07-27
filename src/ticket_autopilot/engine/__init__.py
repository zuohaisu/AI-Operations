"""Ticket Autopilot Engine — a tiny, agent-native workflow engine.

Part of the Ticket Autopilot product (package: ticket_autopilot.engine).

The engine turns a declarative YAML workflow (nodes + edges, with a
verify->reject->execute retry loop and human/agent gates) into a runnable
state machine. Drivers (llm / cli / script / mock) do the actual work; the
engine only orchestrates ordering, conditions, retries and durable snapshots.
"""

__version__ = "0.1.0"

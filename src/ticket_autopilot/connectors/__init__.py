"""Thin I/O adapters to external systems.

Adapters only translate between external APIs and the controller's internal
models. They contain no ticket-loop decision logic.
"""

from .github import create_pr
from .plane import build_workflow_yaml, close_ticket, fetch_issue

__all__ = ["build_workflow_yaml", "close_ticket", "create_pr", "fetch_issue"]

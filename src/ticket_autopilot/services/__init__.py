"""Deterministic services.

These modules own the ticket-loop decision logic that must NOT be delegated to an LLM:
ticket validation, run management, worktree management, development verification,
QA verdict handling, and cleanup.
"""

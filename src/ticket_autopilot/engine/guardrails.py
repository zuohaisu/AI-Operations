"""Deterministic policy checks for CLI-backed Engine nodes.

These checks run before ``subprocess.run`` so a workflow cannot delegate sandbox,
permission, or tool policy enforcement to the external CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Iterable, Mapping

DEFAULT_ALLOWED_ROOTS = ["sandbox"]
DEFAULT_TOOL_WHITELIST = ["Read", "Glob", "Grep"]


class SecurityError(Exception):
    """Raised when a CLI node requests capabilities outside Engine policy."""


@dataclass(frozen=True)
class GuardrailPolicy:
    """Workflow-wide capability boundary for CLI driver invocations."""

    allowed_roots: list[str] = field(default_factory=lambda: DEFAULT_ALLOWED_ROOTS.copy())
    read_only: bool = True
    tool_whitelist: list[str] = field(
        default_factory=lambda: DEFAULT_TOOL_WHITELIST.copy()
    )

    @classmethod
    def from_config(cls, config: Mapping | None = None) -> "GuardrailPolicy":
        """Create a policy from a workflow ``guardrails`` mapping.

        Missing keys retain strict defaults. The mapping is intentionally
        workflow-level: individual agents may request fewer capabilities, but
        cannot relax the boundary selected by the workflow owner.
        """
        config = config or {}
        return cls(
            allowed_roots=list(config.get("allowed_roots", DEFAULT_ALLOWED_ROOTS)),
            read_only=config.get("read_only", True),
            tool_whitelist=list(
                config.get("tool_whitelist", DEFAULT_TOOL_WHITELIST)
            ),
        )


def check_cwd(cwd: str, engine_root: str, policy: GuardrailPolicy) -> str:
    """Resolve ``cwd`` and reject paths outside the policy's sandbox roots."""
    target = os.path.realpath(os.path.join(engine_root, cwd))
    roots = [os.path.realpath(os.path.join(engine_root, root))
             for root in policy.allowed_roots]
    if not any(_is_within(target, root) for root in roots):
        raise SecurityError(
            f"cwd '{target}' is outside allowed roots {roots}. "
            "Refusing to spawn CLI outside the designated directory."
        )
    return target


def check_permission_mode(permission_mode: str, policy: GuardrailPolicy) -> None:
    """Reject any non-read-only request while the policy is read-only."""
    if policy.read_only and permission_mode != "read-only":
        raise SecurityError(
            f"permission_mode '{permission_mode}' violates the read-only Engine policy."
        )


def check_tools(tools: Iterable[str], policy: GuardrailPolicy) -> None:
    """Reject node tools not explicitly present in the workflow whitelist."""
    if isinstance(tools, str):
        raise SecurityError("tools must be a list of tool names, not a string.")
    requested = list(tools)
    disallowed = sorted(set(requested) - set(policy.tool_whitelist))
    if disallowed:
        raise SecurityError(
            f"tools {disallowed} are outside the Engine tool whitelist "
            f"{policy.tool_whitelist}."
        )


def _is_within(target: str, root: str) -> bool:
    try:
        return os.path.commonpath([target, root]) == root
    except ValueError:
        # Different drives on Windows, or invalid paths, cannot be contained.
        return False

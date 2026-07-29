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
# This is deliberately not the default AIO-9 whitelist.  It is usable only by
# the Run Manager's worktree-scoped Developer policy.
DEVELOPER_TOOL_WHITELIST = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]
_READ_ONLY_ROLES = frozenset({"planner", "qa"})
_DEVELOPER_ROLE = "developer"
_READ_ONLY_FORBIDDEN_TOOLS = frozenset({"write", "edit", "bash"})


class SecurityError(Exception):
    """Raised when a CLI node requests capabilities outside Engine policy."""


@dataclass(frozen=True)
class GuardrailPolicy:
    """Workflow-wide capability boundary for CLI driver invocations.

    A Developer does not make this policy writable.  The only writable policy
    is created explicitly by ``RunManager.developer_policy`` with an exact
    disposable worktree root; all AIO-9 defaults remain read-only.
    """

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


@dataclass(frozen=True)
class RunExecutionContext:
    """The immutable Run facts needed to bind Developer execution to one tree."""

    run_id: str
    worktree: str
    branch: str


def normalise_role(role: object | None) -> str | None:
    """Recognise only the three role names carrying additional constraints."""
    if not isinstance(role, str):
        return None
    value = role.strip().casefold().replace("_", "-")
    aliases = {"planner": "planner", "qa": "qa", "developer": "developer"}
    return aliases.get(value)


def check_role_boundary(
    role: object | None,
    *,
    cwd: str,
    permission_mode: str,
    tools: Iterable[str],
    run_context: RunExecutionContext | None,
    requested_branch: object | None = None,
) -> None:
    """Apply role restrictions before an Agent CLI can be spawned.

    Unnamed agents retain the AIO-9 generic policy for backwards compatibility.
    Named Planner and QA agents can never gain mutating tools through a broader
    workflow whitelist.  A Developer must present an exact Run context.
    """
    role_name = normalise_role(role)
    requested = list(tools)
    if role_name in _READ_ONLY_ROLES:
        if permission_mode != "read-only":
            raise SecurityError(f"{role_name} is read-only and cannot request {permission_mode!r}")
        forbidden = sorted({tool for tool in requested if tool.casefold() in _READ_ONLY_FORBIDDEN_TOOLS})
        if forbidden:
            raise SecurityError(f"{role_name} cannot request mutating tools: {forbidden}")
        return
    if role_name != _DEVELOPER_ROLE:
        return

    if run_context is None:
        raise SecurityError("developer requires a disposable Run execution context")
    worktree = os.path.realpath(run_context.worktree)
    if not _is_within(cwd, worktree):
        raise SecurityError("developer cwd is outside its designated disposable worktree")
    if run_context.branch.casefold() in {"main", "master"}:
        raise SecurityError("developer cannot target a protected branch")
    if requested_branch is not None:
        if not isinstance(requested_branch, str) or requested_branch != run_context.branch:
            raise SecurityError("developer requested a branch other than its Run branch")
        if requested_branch.casefold() in {"main", "master"}:
            raise SecurityError("developer cannot target a protected branch")
    if permission_mode not in {"read-only", "write"}:
        raise SecurityError(f"developer requested unsupported permission mode {permission_mode!r}")
    disallowed = sorted(set(requested) - set(DEVELOPER_TOOL_WHITELIST))
    if disallowed:
        raise SecurityError(f"developer tools outside its role whitelist: {disallowed}")


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

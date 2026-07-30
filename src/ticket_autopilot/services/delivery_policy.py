"""Actor-aware delivery policy for review, override, push, and merge actions.

The safety boundary is the actor, not a blanket ban on delivery actions:
agents cannot authorize remote mutations, while a repository owner can give a
specific, auditable instruction for one action.  Pending QA or visual review
remains visible evidence and never masquerades as PASS, but it does not prevent
creation of a Draft PR.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


QA_PENDING = "QA_PENDING"
HUMAN_VISUAL_REVIEW_PENDING = "HUMAN_VISUAL_REVIEW_PENDING"
READY_FOR_REVIEW = "READY_FOR_REVIEW"
USER_OVERRIDE_APPROVED = "USER_OVERRIDE_APPROVED"
MERGE_AUTHORIZED_BY_USER = "MERGE_AUTHORIZED_BY_USER"
DIFF_SPLIT_REQUIRED = "DIFF_SPLIT_REQUIRED"
TECHNICAL_BLOCKED = "TECHNICAL_BLOCKED"

_OWNER_ACTIONS = frozenset({"visual_accept", "push_feature_branch", "create_draft_pr", "override_gate", "merge"})


class DeliveryAuthorizationError(ValueError):
    """A remote delivery action has no valid repository-owner authorization."""


def require_user_authorization(
    authorization: Mapping[str, Any] | None,
    *,
    action: str,
) -> dict[str, Any]:
    """Validate and return a secret-free audit record for one remote action."""
    if action not in _OWNER_ACTIONS:
        raise DeliveryAuthorizationError(f"unsupported delivery action: {action}")
    if not isinstance(authorization, Mapping):
        raise DeliveryAuthorizationError(
            f"{action} requires explicit repository-owner authorization"
        )
    if authorization.get("approved") is not True:
        raise DeliveryAuthorizationError(f"{action} authorization is not approved")
    if authorization.get("actor_type") != "repository_owner":
        raise DeliveryAuthorizationError(
            f"{action} must be authorized by a repository_owner"
        )
    if authorization.get("action") != action:
        raise DeliveryAuthorizationError(
            f"authorization action must be exactly {action}"
        )

    actor = str(authorization.get("actor") or "").strip()
    reason = str(authorization.get("reason") or "").strip()
    approved_at = str(authorization.get("approved_at") or "").strip()
    if not actor:
        raise DeliveryAuthorizationError("authorization actor is required")
    if not reason:
        raise DeliveryAuthorizationError("authorization reason is required")
    if not approved_at:
        raise DeliveryAuthorizationError("authorization approved_at is required")
    try:
        datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeliveryAuthorizationError(
            "authorization approved_at must be an ISO-8601 timestamp"
        ) from exc

    return {
        "actor": actor,
        "actor_type": "repository_owner",
        "action": action,
        "approved": True,
        "approved_at": approved_at,
        "reason": reason,
    }


def delivery_decision(
    *,
    deterministic_status: str,
    qa_status: str,
    visual_status: str,
    diff_attribution: str = "CLEAN",
    user_authorization: Mapping[str, Any] | None = None,
    technical_blocker: str | None = None,
) -> dict[str, Any]:
    """Return an honest decision without turning quality warnings into authority bans.

    A Draft PR is allowed whenever the remote operation is technically possible
    and the ticket-owned Diff is isolated.  Merge always requires a separate,
    explicit ``merge`` authorization, even when every quality gate is green.
    """
    checks = str(deterministic_status).upper()
    qa = str(qa_status).upper()
    visual = str(visual_status).upper()
    attribution = str(diff_attribution).upper()

    warnings: list[str] = []
    if checks != "PASS":
        warnings.append(f"DETERMINISTIC_CHECKS_{checks}")
    if qa != "PASS":
        warnings.append(QA_PENDING if qa == "PENDING" else f"QA_{qa}")
    if visual not in {"PASS", "NOT_REQUIRED"}:
        warnings.append(
            HUMAN_VISUAL_REVIEW_PENDING
            if visual == "PENDING"
            else f"HUMAN_VISUAL_REVIEW_{visual}"
        )
    if attribution != "CLEAN":
        warnings.append(DIFF_SPLIT_REQUIRED)

    if technical_blocker:
        return {
            "status": TECHNICAL_BLOCKED,
            "draft_pr_allowed": False,
            "merge_allowed": False,
            "override_used": False,
            "warnings": warnings,
            "technical_blocker": technical_blocker,
            "authorization": None,
        }

    authorization = None
    merge_allowed = False
    override_approved = False
    if user_authorization is not None:
        requested_action = str(user_authorization.get("action") or "")
        if requested_action not in {"override_gate", "merge"}:
            raise DeliveryAuthorizationError(
                "delivery decision authorization must target override_gate or merge"
            )
        authorization = require_user_authorization(
            user_authorization, action=requested_action
        )
        merge_allowed = requested_action == "merge"
        override_approved = requested_action == "override_gate"

    draft_pr_allowed = attribution == "CLEAN"
    gates_passed = checks == "PASS" and qa == "PASS" and visual in {
        "PASS",
        "NOT_REQUIRED",
    }
    override_used = bool((merge_allowed or override_approved) and not gates_passed)
    if merge_allowed:
        status = MERGE_AUTHORIZED_BY_USER
    elif override_approved:
        status = USER_OVERRIDE_APPROVED
    elif attribution != "CLEAN":
        status = DIFF_SPLIT_REQUIRED
    elif gates_passed:
        status = READY_FOR_REVIEW
    elif visual == "PENDING":
        status = HUMAN_VISUAL_REVIEW_PENDING
    else:
        status = QA_PENDING

    return {
        "status": status,
        "draft_pr_allowed": draft_pr_allowed,
        "merge_allowed": merge_allowed,
        "override_used": override_used,
        "warnings": warnings,
        "technical_blocker": None,
        "authorization": authorization,
    }

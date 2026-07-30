"""Actor-aware delivery policy tests; no remote action is performed."""

from __future__ import annotations

import pytest

from ticket_autopilot.services.delivery_policy import (
    DIFF_SPLIT_REQUIRED,
    HUMAN_VISUAL_REVIEW_PENDING,
    MERGE_AUTHORIZED_BY_USER,
    QA_PENDING,
    READY_FOR_REVIEW,
    TECHNICAL_BLOCKED,
    USER_OVERRIDE_APPROVED,
    DeliveryAuthorizationError,
    delivery_decision,
    require_user_authorization,
)


def authorization(action: str = "merge") -> dict:
    return {
        "actor": "repo-owner",
        "actor_type": "repository_owner",
        "action": action,
        "approved": True,
        "approved_at": "2026-07-31T00:00:00+08:00",
        "reason": "explicit owner decision",
    }


def test_pending_qa_and_visual_review_warn_but_allow_draft_pr():
    result = delivery_decision(
        deterministic_status="PASS",
        qa_status="PENDING",
        visual_status="PENDING",
    )

    assert result["status"] == HUMAN_VISUAL_REVIEW_PENDING
    assert result["draft_pr_allowed"] is True
    assert result["merge_allowed"] is False
    assert result["warnings"] == [QA_PENDING, HUMAN_VISUAL_REVIEW_PENDING]


def test_green_gates_are_ready_for_review_but_never_self_authorize_merge():
    result = delivery_decision(
        deterministic_status="PASS",
        qa_status="PASS",
        visual_status="PASS",
    )

    assert result["status"] == READY_FOR_REVIEW
    assert result["draft_pr_allowed"] is True
    assert result["merge_allowed"] is False
    assert result["authorization"] is None


def test_owner_can_authorize_merge_with_pending_gates_without_fabricating_pass():
    result = delivery_decision(
        deterministic_status="PASS",
        qa_status="PENDING",
        visual_status="PENDING",
        user_authorization=authorization(),
    )

    assert result["status"] == MERGE_AUTHORIZED_BY_USER
    assert result["merge_allowed"] is True
    assert result["override_used"] is True
    assert result["warnings"] == [QA_PENDING, HUMAN_VISUAL_REVIEW_PENDING]
    assert result["authorization"]["reason"] == "explicit owner decision"


def test_owner_override_is_recorded_without_implicitly_authorizing_merge():
    result = delivery_decision(
        deterministic_status="FAIL",
        qa_status="PENDING",
        visual_status="PENDING",
        user_authorization=authorization("override_gate"),
    )

    assert result["status"] == USER_OVERRIDE_APPROVED
    assert result["draft_pr_allowed"] is True
    assert result["merge_allowed"] is False
    assert result["override_used"] is True
    assert "DETERMINISTIC_CHECKS_FAIL" in result["warnings"]
    assert result["authorization"]["action"] == "override_gate"


def test_diff_attribution_requests_split_instead_of_requirements_block():
    result = delivery_decision(
        deterministic_status="PASS",
        qa_status="PASS",
        visual_status="PASS",
        diff_attribution="SPLIT_REQUIRED",
    )

    assert result["status"] == DIFF_SPLIT_REQUIRED
    assert result["draft_pr_allowed"] is False
    assert result["warnings"] == [DIFF_SPLIT_REQUIRED]


def test_only_real_execution_failure_is_technical_blocked():
    result = delivery_decision(
        deterministic_status="PASS",
        qa_status="PENDING",
        visual_status="PENDING",
        technical_blocker="Git credentials rejected by the remote",
    )

    assert result["status"] == TECHNICAL_BLOCKED
    assert result["draft_pr_allowed"] is False
    assert result["technical_blocker"] == "Git credentials rejected by the remote"


@pytest.mark.parametrize("patch", [
    {"approved": False},
    {"actor_type": "developer_agent"},
    {"action": "push_feature_branch"},
    {"approved_at": "not-a-timestamp"},
    {"reason": ""},
])
def test_invalid_or_agent_merge_authorization_is_rejected(patch):
    candidate = authorization()
    candidate.update(patch)

    with pytest.raises(DeliveryAuthorizationError):
        require_user_authorization(candidate, action="merge")

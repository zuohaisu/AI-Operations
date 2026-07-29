"""Deterministic acceptance evidence for the AIO-10 Plane ticket contract gate."""

from __future__ import annotations

from copy import deepcopy
import json
from unittest import mock

import pytest

from ticket_autopilot.connectors import plane
from ticket_autopilot.engine.engine import Engine
from ticket_autopilot.services import ticket_contract


VALID_DESCRIPTION = """## Goal
Make Plane intake deterministic before an Agent can run.

## Scope
- Map the ticket description into ticket-spec.json.

## Out-of-scope
- Do not create a branch or pull request.

## Risk Tier
R1

## Acceptance Criteria
- [ ] AC-1: A complete Plane ticket produces a schema-valid ticket-spec.
- [ ] AC-2: Invalid tickets are blocked before Agent dispatch.

## Verification
- AC-1: automated: `python3 -m pytest tests/test_ticket_contract.py -q`
- AC-2: inspection: `assert planner_executor_qa_calls == 0`

## Repository
`zuohaisu/AI-Operations`

## Required Checks
- `python3 -m pytest tests/test_ticket_contract.py -q`
- `python3 -m pytest -q`

## Constraints
- max_fix_attempts: 2
- allow_main_push: false
"""


def valid_issue(**overrides):
    issue = {
        "id": "d2974231-04b4-4f8b-b8ef-22aac2c3bf5b",
        "identifier": "AIO-10",
        "name": "AIO-10 deterministic ticket contract gate",
        "description": VALID_DESCRIPTION,
        "state": {"name": "In Progress", "group": "started"},
    }
    issue.update(overrides)
    return issue


def without_section(description: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = description.index(marker)
    next_heading = description.find("\n## ", start + len(marker))
    return description[:start] + ("" if next_heading == -1 else description[next_heading + 1:])


def test_complete_r1_ticket_maps_to_schema_valid_traceable_ticket_spec():
    result = ticket_contract.preflight_plane_issue(valid_issue())

    assert result["status"] == "READY"
    spec = result["ticket_spec"]
    assert ticket_contract.validate_ticket_spec(spec) == (True, [])
    assert spec["issue_key"] == "AIO-10"
    assert spec["source_issue"]["id"] == "d2974231-04b4-4f8b-b8ef-22aac2c3bf5b"
    assert spec["goal"] in VALID_DESCRIPTION
    assert spec["repository"] == "zuohaisu/AI-Operations"
    assert spec["provenance"]["repository"] == "description#Repository"
    assert spec["acceptance_criteria"][0]["id"] == "AC-1"
    assert spec["verification"][0]["command"] == "python3 -m pytest tests/test_ticket_contract.py -q"


@pytest.mark.parametrize("heading", [
    "Goal", "Scope", "Out-of-scope", "Acceptance Criteria", "Verification", "Repository",
])
def test_missing_required_fields_block_before_any_engine_agent_dispatch(heading):
    issue = valid_issue(description=without_section(VALID_DESCRIPTION, heading))

    with mock.patch.object(Engine, "_dispatch") as dispatch:
        result = ticket_contract.preflight_plane_issue(issue)

    assert result["status"] == "BLOCKED_REQUIREMENTS"
    assert result["ticket_spec"] is None
    assert result["errors"][0]["field"] in {heading.casefold().replace("-", "_").replace(" ", "_"), "acceptance_criteria"}
    dispatch.assert_not_called()  # Planner / Executor / QA remain at zero calls.


@pytest.mark.parametrize("risk_tier", ["R2", "R3"])
def test_r2_and_r3_are_blocked_for_human_risk_decision(risk_tier):
    result = ticket_contract.preflight_plane_issue(
        valid_issue(description=VALID_DESCRIPTION.replace("\nR1\n", f"\n{risk_tier}\n"))
    )

    assert result["status"] == "BLOCKED_NEEDS_HUMAN"
    assert result["errors"][0]["code"] == "RISK_NOT_AUTOMATABLE"


def test_manual_verification_is_blocked_before_agent_dispatch():
    issue = valid_issue(description=VALID_DESCRIPTION.replace(
        "AC-2: inspection: `assert planner_executor_qa_calls == 0`",
        "AC-2: manual: PM clicks the final approval button",
    ))

    with mock.patch.object(Engine, "_dispatch") as dispatch:
        result = ticket_contract.preflight_plane_issue(issue)

    assert result["status"] == "BLOCKED_REQUIREMENTS"
    assert result["errors"][0]["code"] == "MANUAL_VERIFICATION"
    dispatch.assert_not_called()


def test_cancelled_ticket_is_blocked_without_agent_dispatch():
    with mock.patch.object(Engine, "_dispatch") as dispatch:
        result = ticket_contract.preflight_plane_issue(valid_issue(state={"name": "Cancelled"}))

    assert result["status"] == "BLOCKED_NEEDS_HUMAN"
    assert result["errors"][0]["code"] == "ISSUE_CANCELLED"
    dispatch.assert_not_called()


def test_serialization_round_trip_preserves_load_bearing_fields():
    spec = ticket_contract.preflight_plane_issue(valid_issue())["ticket_spec"]
    restored = json.loads(json.dumps(spec))

    assert ticket_contract.validate_ticket_spec(restored) == (True, [])
    assert restored["schema_version"] == spec["schema_version"]
    assert restored["issue_key"] == spec["issue_key"]
    assert restored["repository"] == spec["repository"]
    assert [item["id"] for item in restored["acceptance_criteria"]] == ["AC-1", "AC-2"]
    assert restored["required_checks"] == spec["required_checks"]
    assert restored["constraints"] == {"max_fix_attempts": 2, "allow_main_push": False}


def test_optional_scope_constraints_are_preserved_for_development_verification():
    description = VALID_DESCRIPTION.replace(
        "- allow_main_push: false\n",
        "- allow_main_push: false\n- forbidden_paths: `secrets/**`, `.github/workflows/**`\n- max_changed_files: 4\n",
    )

    spec = ticket_contract.preflight_plane_issue(valid_issue(description=description))["ticket_spec"]

    assert spec["constraints"]["forbidden_paths"] == ["secrets/**", ".github/workflows/**"]
    assert spec["constraints"]["max_changed_files"] == 4


def test_schema_subset_rejects_contract_that_allows_main_push():
    spec = ticket_contract.map_plane_issue(valid_issue())
    spec["constraints"]["allow_main_push"] = True

    valid, errors = ticket_contract.validate_ticket_spec(spec)

    assert not valid
    assert any("allow_main_push" in error for error in errors)


def test_connector_backed_preflight_reuses_aio8_fetch_issue_without_reimplementing_http():
    issue = valid_issue()
    with mock.patch.object(plane, "fetch_issue", return_value=issue) as fetch:
        result = ticket_contract.fetch_and_preflight_plane_issue(
            issue["id"], workspace="hspace", project_id="project-id", api_key="not-a-real-key"
        )

    assert result["status"] == "READY"
    fetch.assert_called_once_with(
        issue["id"], workspace="hspace", project_id="project-id", api_key="not-a-real-key"
    )
    source = ticket_contract.__file__
    assert "urllib" not in open(source, encoding="utf-8").read()

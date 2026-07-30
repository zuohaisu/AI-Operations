"""AIO-18 Prompt source and Planner call-count tests; no Agent is spawned."""
from __future__ import annotations

from pathlib import Path

from ticket_autopilot.services.prompt_resolver import PromptResolver


SPEC = {"repository": "zuohaisu/AI-Operations", "issue_key": "AIO-18"}
ISSUE = {"id": "plane-18", "identifier": "AIO-18", "description": "ticket source"}


def generated(role: str) -> str:
    boundary = "Developer implements" if role == "dev" else "QA accepts independently"
    return f"立即执行: {boundary} AIO-18 only in zuohaisu/AI-Operations; attribute Diff and dirty tree; conditional visual evidence gate."


def resolver(tmp_path: Path) -> PromptResolver:
    (tmp_path / "tasks").mkdir()
    return PromptResolver(tmp_path)


def test_existing_prompts_bypass_planner_and_copy_bytes(tmp_path: Path):
    service = resolver(tmp_path)
    dev, acceptance = service.canonical_paths("AIO-18").values()
    dev.write_bytes(b"dev\n\xff")
    acceptance.write_bytes(b"acceptance\n")
    calls = []

    result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE,
                             planner=lambda **kwargs: calls.append(kwargs))

    assert calls == []
    assert result["status"] == "READY"
    assert result["visual_evidence"]["status"] == "HUMAN_VISUAL_REVIEW_PENDING"
    assert result["visual_evidence"]["draft_pr_allowed"] is True
    assert result["visual_evidence"]["available_user_actions"] == [
        "record_human_visual_pass",
        "override_gate",
    ]
    assert result["prompts"]["dev"]["source"] == "existing_file"
    artifact = tmp_path / result["artifact_dir"]
    assert (artifact / "dev-prompt.md").read_bytes() == b"dev\n\xff"
    assert (artifact / "acceptance-prompt.md").read_bytes() == b"acceptance\n"


def test_planner_generates_only_missing_role_without_changing_existing(tmp_path: Path):
    service = resolver(tmp_path)
    dev = service.canonical_paths("AIO-18")["dev"]
    dev.write_text("existing developer content\n", encoding="utf-8")
    calls = []

    def planner(**kwargs):
        calls.append(kwargs)
        return {"acceptance": generated("acceptance")}

    result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner)

    assert calls[0]["missing_roles"] == ("acceptance",)
    assert dev.read_text(encoding="utf-8") == "existing developer content\n"
    assert result["prompts"]["dev"]["source"] == "existing_file"
    assert result["prompts"]["acceptance"]["source"] == "planner_generated"


def test_planner_generates_both_prompts_into_artifacts_only(tmp_path: Path):
    service = resolver(tmp_path)
    before = sorted((tmp_path / "tasks").iterdir())
    calls = []

    def planner(**kwargs):
        calls.append(kwargs)
        return {"dev": generated("dev"), "acceptance": generated("acceptance")}

    result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner)

    assert calls[0]["missing_roles"] == ("dev", "acceptance")
    assert result["status"] == "READY"
    assert sorted((tmp_path / "tasks").iterdir()) == before
    artifact = tmp_path / result["artifact_dir"]
    assert (artifact / "dev-prompt.md").read_text().startswith("立即执行")
    assert (artifact / "acceptance-prompt.md").read_text().startswith("立即执行")


def test_planner_failure_or_missing_role_is_hard_break(tmp_path: Path):
    service = resolver(tmp_path)
    result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE,
                             planner=lambda **_kwargs: {"dev": generated("dev")})
    assert result["status"] == "HARD_BREAK_PLANNER"
    assert "acceptance" in result["hard_break_reason"]
    assert result["prompts"] == {}


def test_exact_three_digit_task_mapping(tmp_path: Path):
    service = resolver(tmp_path)
    paths = service.canonical_paths("AIO-18")
    assert paths["dev"].name == "AIO-018-dev-prompt.md"
    assert paths["acceptance"].name == "AIO-018-acceptance-prompt.md"

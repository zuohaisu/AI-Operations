"""AIO-18 Prompt source and Planner call-count tests; no Agent is spawned."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from ticket_autopilot.services import prompt_resolver as prompt_resolver_module
from ticket_autopilot.services.prompt_resolver import PromptResolver


SPEC = {"repository": "zuohaisu/AI-Operations", "issue_key": "AIO-18"}
ISSUE = {"id": "plane-18", "identifier": "AIO-18", "description": "ticket source"}


def generated(role: str) -> str:
    boundary = "Developer implements" if role == "dev" else "QA accepts independently"
    return f"立即执行: {boundary} AIO-18 only in zuohaisu/AI-Operations; attribute Diff and dirty tree; conditional visual evidence gate."


def resolver(tmp_path: Path) -> PromptResolver:
    (tmp_path / "tasks").mkdir()
    return PromptResolver(tmp_path)


def preparing_metadata(issue_key: str = "AIO-26", **overrides: object) -> dict[str, object]:
    metadata = {
        "schema_version": "1.0",
        "issue_key": issue_key,
        "status": "PREPARING",
        "planner_outcome": "pending",
        "hard_break_reason": None,
        "preserved": {"evidence": "keep-me"},
    }
    metadata.update(overrides)
    return metadata


def write_metadata(service: PromptResolver, name: str, metadata: dict[str, object]) -> Path:
    artifact_dir = service.artifacts_root / name
    artifact_dir.mkdir(parents=True)
    path = artifact_dir / "prompt-metadata.json"
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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
    assert result["owner_pid"] == os.getpid()
    created_at = datetime.fromisoformat(str(result["created_at"]))
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
    assert result["prompts"]["dev"]["source"] == "existing_file"
    artifact = tmp_path / result["artifact_dir"]
    persisted_metadata = json.loads((artifact / "prompt-metadata.json").read_text(encoding="utf-8"))
    assert persisted_metadata["owner_pid"] == os.getpid()
    assert persisted_metadata["created_at"] == result["created_at"]
    assert (artifact / "dev-prompt.md").read_bytes() == b"dev\n\xff"
    assert (artifact / "acceptance-prompt.md").read_bytes() == b"acceptance\n"


def test_planner_generates_only_missing_role_without_changing_existing(tmp_path: Path):
    service = resolver(tmp_path)
    paths = service.canonical_paths("AIO-18")
    dev = paths["dev"]
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
    # The generated acceptance Prompt is persisted to its canonical tasks/ file.
    assert paths["acceptance"].read_text(encoding="utf-8").startswith("立即执行")


def test_planner_generates_both_prompts_into_canonical_tasks_and_artifacts(tmp_path: Path):
    service = resolver(tmp_path)
    paths = service.canonical_paths("AIO-18")
    calls = []

    def planner(**kwargs):
        calls.append(kwargs)
        return {"dev": generated("dev"), "acceptance": generated("acceptance")}

    result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner)

    assert calls[0]["missing_roles"] == ("dev", "acceptance")
    assert result["status"] == "READY"
    # Generated Prompts now live at their canonical tasks/ paths so Run reads them.
    for role in ("dev", "acceptance"):
        assert paths[role].read_text(encoding="utf-8").startswith("立即执行")
        assert result["prompts"][role]["source"] == "planner_generated"
        assert result["prompts"][role]["canonical_path"] == str(paths[role].relative_to(tmp_path))
    artifact = tmp_path / result["artifact_dir"]
    # The owned Run artifact keeps a byte-identical mirror for provenance.
    assert (artifact / "dev-prompt.md").read_bytes() == paths["dev"].read_bytes()
    assert (artifact / "acceptance-prompt.md").read_bytes() == paths["acceptance"].read_bytes()


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


def test_live_preparing_owner_remains_single_flight_blocker(tmp_path: Path):
    service = resolver(tmp_path)
    metadata_path = write_metadata(service, "live-owner", preparing_metadata(owner_pid=os.getpid()))
    original = metadata_path.read_bytes()

    assert service.has_active_run() is True
    assert metadata_path.read_bytes() == original


def test_dead_preparing_owner_is_finalized_in_place(tmp_path: Path):
    service = resolver(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    metadata_path = write_metadata(service, "dead-owner", preparing_metadata(owner_pid=child.pid))

    assert service.has_active_run() is False
    assert metadata_path.is_file()
    recovered = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert recovered["status"] == "HARD_BREAK_PLANNER"
    assert recovered["planner_outcome"] == "failed"
    assert recovered["hard_break_reason"]
    assert "orphan recovery" in recovered["hard_break_reason"]
    assert recovered["issue_key"] == "AIO-26"
    assert recovered["preserved"] == {"evidence": "keep-me"}


def test_stale_legacy_preparing_owner_is_recovered_but_recent_one_blocks(tmp_path: Path, monkeypatch):
    service = resolver(tmp_path)
    now = 2_000_000.0
    monkeypatch.setattr(prompt_resolver_module.time, "time", lambda: now)
    stale_path = write_metadata(service, "stale-legacy", preparing_metadata())
    recent_path = write_metadata(service, "recent-legacy", preparing_metadata())
    os.utime(stale_path, (now - 1800.001, now - 1800.001))
    os.utime(recent_path, (now - 1800, now - 1800))

    assert service.has_active_run() is True
    assert stale_path.is_file()
    stale = json.loads(stale_path.read_text(encoding="utf-8"))
    assert stale["status"] == "HARD_BREAK_PLANNER"
    assert stale["planner_outcome"] == "failed"
    assert stale["hard_break_reason"]
    assert stale["issue_key"] == "AIO-26"
    assert json.loads(recent_path.read_text(encoding="utf-8"))["status"] == "PREPARING"

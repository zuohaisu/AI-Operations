"""AIO-18 QA read-only probe: fills AC evidence not covered by shipped tests.

Runs against the working tree without modifying repository files; all
filesystem writes go to a pytest-style temp dir under .qa-tmp/probe-home.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ticket_autopilot.connectors import plane  # noqa: E402
from ticket_autopilot.services.prompt_resolver import PromptResolver  # noqa: E402
from ticket_autopilot.web import LocalConfig, TicketBoard  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, evidence: str) -> None:
    RESULTS.append((name, bool(condition), evidence))


def raw(state_group: str = "started") -> dict:
    return {
        "id": f"item-{state_group}", "name": "AIO ticket", "description": None, "identifier": None,
        "description_html": """<h2>Goal</h2><p>deterministic intake</p><h2>Scope</h2><ul><li>Impact closure covers callers and consumers, triggered guards, executable dependencies, Given when then behavioral AC, observed checked-at semantic mapping, and global serial resource 127.0.0.1:8765.</li></ul>
<h2>Out-of-scope</h2><ul><li>no PR</li></ul><h2>Risk Tier</h2><p>R1</p><h2>Acceptance Criteria</h2><ul><li>AC-1: works</li></ul>
<h2>Verification</h2><ul><li>AC-1: automated: <code>pytest -q</code></li></ul><h2>Repository</h2><p><code>zuohaisu/AI-Operations</code></p>
<h2>Required Checks</h2><ul><li><code>pytest -q</code></li></ul><h2>Constraints</h2><ul><li>max_fix_attempts: 0</li><li>allow_main_push: false</li></ul>""",
        "description_stripped": "flat preview", "sequence_id": 18,
        "project": {"identifier": "AIO"}, "state": {"id": f"{state_group}-id", "group": state_group},
        "priority": "high",
    }


SPEC = {"repository": "zuohaisu/AI-Operations", "issue_key": "AIO-18"}
ISSUE = {"id": "plane-18", "identifier": "AIO-18"}
VALID = ("立即执行: Developer implements and QA accepts AIO-18 only in zuohaisu/AI-Operations; "
         "attribute diff and dirty tree; conditional visual evidence gate.")


def fresh_resolver(base: Path, name: str) -> PromptResolver:
    root = base / name
    (root / "tasks").mkdir(parents=True)
    return PromptResolver(root)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="aio18-probe-", dir=str(REPO / ".qa-tmp")))
    try:
        # AC-3 direction not covered by shipped tests: only the dev Prompt is missing.
        service = fresh_resolver(base, "missing-dev")
        service.canonical_paths("AIO-18")["acceptance"].write_text("existing acceptance\n", encoding="utf-8")
        calls: list[dict] = []

        def planner_dev(**kwargs):
            calls.append(kwargs)
            return {"dev": VALID}

        result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner_dev)
        check("AC-3 missing-dev planner called once for dev only",
              len(calls) == 1 and calls[0]["missing_roles"] == ("dev",),
              f"calls={len(calls)} missing_roles={calls[0]['missing_roles'] if calls else None}")
        check("AC-3 missing-dev sources", result["status"] == "READY"
              and result["prompts"]["dev"]["source"] == "planner_generated"
              and result["prompts"]["acceptance"]["source"] == "existing_file",
              json.dumps({r: result["prompts"][r]["source"] for r in result["prompts"]}))
        check("AC-3 existing acceptance unchanged",
              service.canonical_paths("AIO-18")["acceptance"].read_text(encoding="utf-8") == "existing acceptance\n",
              "byte-identical canonical file")

        # AC-5: exception, timeout, malformed output each hard-break with 0 downstream calls.
        for label, planner in (
            ("exception", mock.Mock(side_effect=RuntimeError("planner crashed"))),
            ("timeout", mock.Mock(side_effect=TimeoutError("planner timed out"))),
            ("malformed", mock.Mock(return_value="not-an-object")),
            ("missing-role", mock.Mock(return_value={})),
        ):
            service = fresh_resolver(base, f"hard-break-{label}")
            result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner)
            metadata = json.loads((service.repository / result["artifact_dir"] / "prompt-metadata.json").read_text())
            check(f"AC-5 {label} -> HARD_BREAK_PLANNER",
                  result["status"] == "HARD_BREAK_PLANNER" and result["prompts"] == {}
                  and metadata["status"] == "HARD_BREAK_PLANNER" and bool(result["hard_break_reason"]),
                  f"status={result['status']} reason={result['hard_break_reason']!r} planner_calls={planner.call_count}")
            check(f"AC-5 {label} reason has no secret",
                  "secret" not in str(result["hard_break_reason"]).casefold(), str(result["hard_break_reason"]))

        # AC-4: missing_both -> exactly one Planner call, two non-empty role-separated artifacts.
        service = fresh_resolver(base, "missing-both")
        both_calls: list[dict] = []

        def planner_both(**kwargs):
            both_calls.append(kwargs)
            return {"dev": VALID, "acceptance": VALID + " QA accepts independently."}

        result = service.prepare(issue_key="AIO-18", ticket_spec=SPEC, source_issue=ISSUE, planner=planner_both)
        artifact = service.repository / result["artifact_dir"]
        check("AC-4 missing_both planner call count == 1",
              len(both_calls) == 1 and both_calls[0]["missing_roles"] == ("dev", "acceptance"),
              f"calls={len(both_calls)}")
        check("AC-4 two non-empty artifacts",
              (artifact / "dev-prompt.md").stat().st_size > 0 and (artifact / "acceptance-prompt.md").stat().st_size > 0,
              str(artifact.relative_to(service.repository)))

        # AC-6: cancelled ticket refused at the board layer with 0 downstream calls.
        home = base / "board-home"
        settings = LocalConfig(home)
        settings.save({"plane": {"workspace": "hspace", "project": "project", "api_key": "k"}})
        repo = base / "board-repo"
        (repo / "tasks").mkdir(parents=True)
        planner_spy = mock.Mock()
        board = TicketBoard(settings, repository=repo, planner=planner_spy)
        cancelled = plane.normalize_work_item(raw("cancelled"))
        with mock.patch("ticket_autopilot.web.plane.fetch_issue", return_value=cancelled):
            result = board.prepare(cancelled["id"])
        check("AC-6 cancelled refused, downstream 0",
              result["status"] == "BLOCKED_REQUIREMENTS" and result["developer_calls"] == 0
              and result["qa_calls"] == 0 and planner_spy.call_count == 0,
              json.dumps(result))

        runs = repo / ".ticket-autopilot" / "runs"
        check("AC-6 cancelled created no Run artifacts",
              not runs.exists() or not any(runs.iterdir()), str(runs))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    failed = [entry for entry in RESULTS if not entry[1]]
    for name, ok, evidence in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {evidence}")
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

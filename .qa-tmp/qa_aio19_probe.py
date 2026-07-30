"""AIO-19 read-only QA probe: behavior evidence beyond the shipped test suite.

Covers the acceptance-matrix variants that tests/integration/test_web_agent_loop.py
does not assert directly:
  P1  AC-4 malformed QA verdict -> HARD_BREAK (QA_MALFORMED_OUTPUT), no FAIL consumed
  P2  AC-4 developer process timeout/error -> HARD_BREAK (DEVELOPER_PROCESS_FAILED)
  P3  AC-5 commit message contains issue key; staged set == changed_files; branch/SHA recorded
  P4  AC-6 empty diff after eligible checks -> BLOCKED, Commit=0
  P5  AC-2 second QA receives fresh full diff + qa_attempt=2 (new context, not carry-over)
All Agents are fakes; the repository is a throwaway fixture. No file in the real
repo is modified.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticket_autopilot.services.web_agent_loop import HARD_BREAK, WebAgentLoop
from tests.test_development_verifier import TemporaryRun
from tests.test_run_worktree import ticket_spec as base_ticket_spec


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def spec():
    value = deepcopy(base_ticket_spec())
    value["issue_key"] = value["source_issue"]["key"] = "AIO-19"
    return value


def verdict(ticket, run_id, attempt, outcome="PASS"):
    return {"schema_version": "1.0", "issue_key": ticket["issue_key"], "run_id": run_id,
            "qa_attempt": attempt, "verdict": outcome,
            "acceptance_criteria": [{"id": item["id"], "status": "PASS" if outcome == "PASS" else "FAIL",
                                     "evidence": ["fake"]} for item in ticket["acceptance_criteria"]],
            "findings": [] if outcome == "PASS" else [
                {"id": "QA-1", "severity": "major", "type": "bug", "acceptance_criterion_id": "AC-1",
                 "summary": "original", "evidence": {"file": "change.txt"}, "required_fix": "fix"}],
            "non_blocking_comments": [], "recommended_next_state": "PASS" if outcome == "PASS" else "FIXING"}


def build(fixture, developer, checker, qa):
    return WebAgentLoop(fixture.manager, developer=developer, checker=checker, qa=qa,
                        thread_factory=ImmediateThread)


def load_state(fixture, run_id):
    import json
    return json.loads((fixture.repo / ".ticket-autopilot" / "runs" / run_id /
                       "web-agent-loop-state-v1.json").read_text())


def default_developer(**kwargs):
    (Path(kwargs["run"]["worktree"]) / "change.txt").write_text("changed", encoding="utf-8")
    return {"process_identity": "dev"}


def default_checker(run, *, qa_attempt, diff="diff --git a/change.txt b/change.txt\n+changed\n"):
    return {"verified": True, "checks": [{"exit_code": 0}], "changed_files": ["change.txt"], "diff": diff}


results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


# P1: malformed QA verdict -> HARD_BREAK, does not consume a FAIL round
fixture = TemporaryRun()
try:
    service = build(fixture, default_developer, default_checker,
                    lambda **kwargs: {"schema_version": "1.0", "verdict": "PASS"})  # missing keys
    run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
    state = load_state(fixture, run_id)
    check("P1 malformed verdict is HARD_BREAK",
          state["status"] == HARD_BREAK and state["hard_break"]["code"] == "QA_MALFORMED_OUTPUT",
          f"status={state['status']} code={state.get('hard_break', {}).get('code')}")
    check("P1 no FAIL round consumed / no commit",
          not state["attempts"] and "commit" not in state and state["qa_attempt"] == 1)
finally:
    fixture.close()

# P2: developer process error (models timeout/permission failure) -> HARD_BREAK
fixture = TemporaryRun()
try:
    def broken_developer(**kwargs):
        raise TimeoutError("agent timed out")
    service = build(fixture, broken_developer, default_checker, lambda **kwargs: None)
    run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
    state = load_state(fixture, run_id)
    check("P2 developer timeout is HARD_BREAK",
          state["status"] == HARD_BREAK and state["hard_break"]["code"] == "DEVELOPER_PROCESS_FAILED",
          f"code={state.get('hard_break', {}).get('code')}")
    check("P2 qa never called / no commit", not state["qa_processes"] and "commit" not in state)
finally:
    fixture.close()

# P3: PASS path commit semantics - message has issue key, staged set exact, SHA real
fixture = TemporaryRun()
try:
    qa_inputs = []

    def qa_pass(**kwargs):
        qa_inputs.append(kwargs)
        return verdict(spec(), kwargs["run"]["run_id"], kwargs["qa_attempt"], "PASS")

    service = build(fixture, default_developer, default_checker, qa_pass)
    run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
    state = load_state(fixture, run_id)
    worktree = Path(state and fixture.manager.load_run(run_id).worktree)
    log = fixture.git("log", "-1", "--pretty=%s", cwd=worktree).stdout.strip()
    shown = fixture.git("show", "--name-only", "--pretty=", "HEAD", cwd=worktree).stdout.split()
    check("P3 commit after PASS with issue key in message",
          state["status"] == "PASS" and "AIO-19" in log, f"message={log!r}")
    check("P3 staged/committed set == ticket-owned changed files",
          shown == ["change.txt"] and state["commit"]["changed_files"] == ["change.txt"],
          f"committed={shown}")
    sha = fixture.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
    record = fixture.manager.load_run(run_id)
    check("P3 recorded branch/SHA match repository",
          state["commit"]["sha"] == sha and state["commit"]["branch"] == record.branch,
          f"branch={state['commit']['branch']} sha_match={state['commit']['sha'] == sha}")
finally:
    fixture.close()

# P4: empty diff -> BLOCKED before QA, Commit=0
fixture = TemporaryRun()
try:
    qa_calls = []

    def checker_empty(run, *, qa_attempt):
        return {"verified": True, "checks": [{"exit_code": 0}], "changed_files": ["change.txt"], "diff": "  "}

    service = build(fixture, default_developer, checker_empty,
                    lambda **kwargs: qa_calls.append(kwargs))
    run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
    state = load_state(fixture, run_id)
    check("P4 empty diff is BLOCKED with zero QA/Commit calls",
          state["status"] == "BLOCKED" and not qa_calls and "commit" not in state,
          f"reason={state.get('reason')}")
finally:
    fixture.close()

# P5: after first FAIL, second QA is a fresh context with full diff and qa_attempt=2
fixture = TemporaryRun()
try:
    qa_inputs = []
    outcomes = ["FAIL", "PASS"]

    def qa_two(**kwargs):
        qa_inputs.append(kwargs)
        return verdict(spec(), kwargs["run"]["run_id"], kwargs["qa_attempt"], outcomes.pop(0))

    service = build(fixture, default_developer, default_checker, qa_two)
    run_id = service.start(spec(), developer_prompt="dev", qa_prompt="qa")["run_id"]
    state = load_state(fixture, run_id)
    check("P5 second QA re-reads full diff with qa_attempt=2",
          len(qa_inputs) == 2 and qa_inputs[1]["qa_attempt"] == 2
          and qa_inputs[1]["diff"].startswith("diff --git") and qa_inputs[1]["permission_mode"] == "read-only",
          f"attempts={[q['qa_attempt'] for q in qa_inputs]}")
    check("P5 developer round 2 received verbatim round-1 findings",
          state["attempts"][0]["findings"][0]["summary"] == "original")
finally:
    fixture.close()

failed = [item for item in results if not item[1]]
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
print(f"\n{len(results) - len(failed)}/{len(results)} probes passed")
sys.exit(1 if failed else 0)

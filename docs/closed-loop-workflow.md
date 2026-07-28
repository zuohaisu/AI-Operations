# Closed-Loop Workflow Definition

This is the authoritative **operational** definition for the Ticket Autopilot
closed loop. `IDEA.md` remains the project charter and `AGENTS.md` remains the
working charter; this document maps their stages to the repository's actual
Engine and Connector entities. A stage is closed only when its stated evidence
gate is met. A missing Connector or gate is `BLOCKED`, never evidence of
success.

## Current boundary and reuse decision

The existing reusable controller is `src/ticket_autopilot/engine/engine.py`:
it interprets the declarative workflows and their conditional retry edge. The
existing reusable Plane path is
`src/ticket_autopilot/reference/ticket-pipeline/plane_client.py`, currently
used only by `src/ticket_autopilot/engine/handlers/close_ticket.py`. Per
`research/capability-audit.md`, `connectors/`, `services/`, and `schemas/` are
empty scaffolds, and `src/ticket_autopilot/cli.py` is a stub. Do not replace the
Engine with another controller.

The commands below are evidence inspections, not claims that an unimplemented
stage is live. Use `PYTHONPATH=src python3 -m ticket_autopilot.engine run
src/ticket_autopilot/workflows/ticket-pipeline.yaml --mock --params '{"ticket_id":"DEMO-1"}'` to
exercise the existing Engine control flow without contacting Plane or an LLM.

## Required stage mapping

| Stage | Responsible entity and tool / command | How the current flow executes | Evidence gate |
| --- | --- | --- | --- |
| 1. Ticket intake and contract | **Current Plane adapter:** `src/ticket_autopilot/reference/ticket-pipeline/plane_client.py` (`get_issue` / `list_issues`), reused only by `src/ticket_autopilot/engine/handlers/close_ticket.py`. **Target:** `src/ticket_autopilot/connectors/plane.py` (not yet present). Inspect with `grep -n 'def get_issue' src/ticket_autopilot/reference/ticket-pipeline/plane_client.py; grep -n 'def list_issues' src/ticket_autopilot/reference/ticket-pipeline/plane_client.py`. | The YAML currently accepts only `params.ticket_id`; it has no intake node, ticket-contract schema, or structural validator. A future thin Plane Connector must read the issue and validate the contract before passing it to `plan`. | Required structured ticket fields are complete and validated. **Current status: BLOCKED**—the repository cannot produce this evidence yet. |
| 2. Plan | `planner` agent, `plan` node, `driver: llm` in `src/ticket_autopilot/workflows/ticket-pipeline.yaml`; the Hermes alternative is the same `plan` node in `src/ticket_autopilot/workflows/ticket-pipeline-hermes.yaml`. Inspect with `grep -n 'id: plan' src/ticket_autopilot/workflows/ticket-pipeline*.yaml; grep -n 'driver: llm' src/ticket_autopilot/workflows/ticket-pipeline.yaml; grep -n 'driver: hermes' src/ticket_autopilot/workflows/ticket-pipeline-hermes.yaml`. | `Engine` resolves `${params.ticket_id}`, runs the planner, and captures its output as `nodes.plan`; the next forward edge enables `execute`. | A non-empty plan text is captured as the `plan` node output. It is not a validated ticket contract; a real run must not bypass the blocked intake gate. |
| 3. Execute / development | `executor` agent and `execute` node in `src/ticket_autopilot/workflows/ticket-pipeline.yaml`; `src/ticket_autopilot/engine/drivers.py::cli_call` invokes `claude`. Its actual configuration is `cwd: ./sandbox`, `permission_mode: read-only`, and tools `Read`, `Glob`, `Grep`. `ticket-pipeline-hermes.yaml` is a Hermes variant whose sandbox is caller-enforced. Verify the CLI guardrail with `python3 -m unittest discover -s src/ticket_autopilot/engine/tests -v`. | `cli_call` resolves the cwd inside the allowed sandbox root, raises `SecurityError` before spawning a CLI outside it, passes `--permission-mode read-only`, and passes `--allowedTools`. The standard workflow therefore cannot write implementation changes. | The current evidence is the enforced sandbox, read-only mode, and tool allowlist, including the `SecurityError` test. This is a safety gate, **not** evidence of completed development; writable worktree/branch execution is still a future thin Connector. |
| 4. Deterministic verification and independent QA | `verifier` agent and `verify` node in both workflow YAML files; standard driver is `llm` with `expect: json`. Inspect with `grep -n 'id: verify' src/ticket_autopilot/workflows/ticket-pipeline*.yaml; grep -n 'expect: json' src/ticket_autopilot/workflows/ticket-pipeline*.yaml; grep -n 'decision.*accept' src/ticket_autopilot/workflows/ticket-pipeline*.yaml`. | The verifier receives the captured plan and execute result and must return JSON with `decision` `accept` or `reject`; the Engine evaluates that decision on the outgoing edges. | Only `verdict.decision == accept` permits the current `close` edge. **Current status: incomplete**—this is an LLM verdict, not deterministic command evidence or independent Codex QA. The independent-QA upgrade belongs to the planned AIO-7 work and must not be represented as present. |
| 5. Bounded fix loop | The `verify` → `execute` edge in both YAML workflows: `kind: loop`, `when: "nodes.verify.decision == 'reject'"`, and `max_retries: ${vars.max_retries}`; `vars.max_retries` is currently `5`. Inspect with `grep -n 'max_retries' src/ticket_autopilot/workflows/ticket-pipeline*.yaml; grep -n 'kind: loop' src/ticket_autopilot/workflows/ticket-pipeline*.yaml; grep -n 'nodes.verify.decision' src/ticket_autopilot/workflows/ticket-pipeline*.yaml`. | `Engine._fire_edges` increments the loop retry count and marks `execute` stale for another run only while below the cap. On exhaustion it stops firing that edge; it does not fabricate an accept or close result. | A reject can re-run execute no more than the configured cap. Exhaustion leaves `close` incomplete and is not success; current code does not yet write a `BLOCKED` ticket result. |
| 6. Pull Request and CI evidence | **No current GitHub Connector or workflow node exists.** The intended reuse path is native GitHub Actions plus `gh` through a future thin GitHub Connector; `research/capability-audit.md` records the local `gh` capability audit. Before relying on this stage, inspect the absence with `find src/ticket_autopilot/connectors -maxdepth 1 -type f -print` and inspect available CLI support with `gh pr create --help` and `gh run list --help`. | This repository's Engine does not create branches, commits, pushes, pull requests, or CI evidence. This document only reserves the integration point; it does not implement it. | A PR exists and its required CI is passing. **Current status: BLOCKED** until the future Connector collects those facts. Never substitute local self-reporting for PR/CI evidence. |
| 7. Ticket status and result | `closer` agent and `close` node use `driver: script`, `entry: close_ticket`; `src/ticket_autopilot/engine/handlers/close_ticket.py::close_ticket` calls `plane_client.add_comment` then `plane_client.set_state(ticket_id, "done")`. Inspect with `grep -nE 'add_comment|set_state.*done' src/ticket_autopilot/engine/handlers/close_ticket.py`. | The `verify` accept edge invokes the script handler, which posts the plan/result comment and attempts to set the Plane ticket to done. It is the only current Engine node that touches Plane. | Plane comment and state-update calls complete successfully. **Current status: not safe for AIO closure:** the reused client has a hard-coded project ID identified in `research/capability-audit.md`; a parameterized Connector and preceding PR/CI/independent-QA evidence are required before this may close a real AIO ticket. |

## Mandatory goal check and retrospective verification

Every work segment—research, planning, implementation, verification, review, or
handoff—must begin its working update with exactly one concise line in this
form, before any other substantive content:

```text
[Goal check] This work advances <closed-loop stage> by <measurable evidence>.
```

If the line cannot name both a closed-loop stage and measurable evidence, stop
and classify the request as a side track; ask for reprioritization. Repeat it
when the deliverable changes, a subsystem is proposed, or work expands beyond
the active ticket.

This is retrospectively checkable for any saved working update, transcript
segment, plan, or handoff artifact. Check its first non-blank line with:

```bash
artifact=path/to/work-update.md
awk 'NF {print; exit}' "$artifact" | grep -Ex '\[Goal check\] This work advances .+ by .+\.'
```

The command exits `0` only when the first non-blank line has the required
shape; a non-zero exit is a missing or malformed goal check. During review,
record the artifact path and command result, confirm that the named stage is
one of the seven stages above, and confirm that the cited evidence actually
exists. This is an audit convention, not a CI gate.

## Explicit exclusions

This definition describes the current v0.1 boundary and does **not** add or
claim: resume, webhook triggers, parallel runs, automatic merge, automatic
deploy, automatic migration, or automatic selection of the next ticket. PRs
remain subject to human review and merge. Credentials, if a future Connector
uses them, are read from environment variables, Keychain, or existing `gh`
authentication; they are never written into this workflow definition.

## Deterministic verification commands

```bash
# Engine loop, input templating, CLI cwd guardrail, and Hermes dispatch tests
python3 -m unittest discover -s src/ticket_autopilot/engine/tests -v

# Confirm the mandatory convention is present in this authoritative definition
grep -n 'Goal check' docs/closed-loop-workflow.md
```

A test or evidence command that fails is `BLOCKED`; it must not be described as
a completed stage.

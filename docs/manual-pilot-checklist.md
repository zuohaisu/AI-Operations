# Manual Pilot Checklist (Phase 1 Web Run)

Use this checklist to manually observe one complete, real Phase 1 Web Run:
one eligible Plane Ticket, one click of **Run**, through Planner → Developer →
deterministic checks → independent QA, to a terminal state. It assumes the
reader already saved local Plane/repository/Agent CLI configuration once (see
[README.md](../README.md)) and complements the authoritative reference in
[docs/closed-loop-workflow.md](closed-loop-workflow.md) and
[docs/run-event-schema.md](run-event-schema.md). If the live UI or terminal
states drift from what is written here, treat the code and those two
documents as authoritative and update this checklist rather than trusting
your memory of it.

## Before Run

- [ ] Confirm no other active Run currently owns this repository. `127.0.0.1:8765`
      is a serial resource: only one Run per repository may be active at a
      time. Run `python -m ticket_autopilot.web status` (or
      `./start-ticket-autopilot status`) and check the Web Timeline for any
      Run whose status is one of `ACTIVE`, `DEVELOPING`, `VERIFYING`, or
      `QA_RUNNING` before proceeding. Do not start a new Run while one is
      active.
- [ ] Start the service:
      ```bash
      python -m ticket_autopilot.web start
      ```
      or `./start-ticket-autopilot start`. The service listens only on
      `http://127.0.0.1:8765/`; it does not accept remote connections.
- [ ] Open `http://127.0.0.1:8765/` in a browser.
- [ ] In the ticket list, select an **eligible** ticket. A ticket is eligible
      when its detail panel's `Eligibility` line reads `Ready to run`; if it
      instead shows a blocking reason (contract, readiness, or risk-tier
      failure), pick a different ticket or resolve the stated reason first.
      The `Run Ticket Autopilot` button stays disabled for an ineligible
      ticket.
- [ ] Note whether `Prompt availability` shows existing Developer/Acceptance
      Prompt files or "missing" — either is fine. This pilot exists to prove
      the normal path, including automatic Planner preparation when a Prompt
      is missing; you do not need to pre-create `tasks/AIO-NNN-*` Prompts.

## During Run

- [ ] Click **Run Ticket Autopilot** exactly once. Do not click it again
      while a Run is in progress.
- [ ] If a Prompt was missing, the UI first shows a `PREPARING` operation
      (Planner generating the missing Prompt) before a Run starts; if both
      Prompts already existed, a Run starts immediately. Either path is
      normal.
- [ ] Watch the Run Timeline populate as an append-only event stream. Confirm
      you can observe, in order, the expected stage progression:
      1. **Planner** — prompt-source/provenance event(s), only when a Prompt
         was generated for this Run.
      2. **Developer** — `development` stage events, ending with an
         `agent_completed` event once the Developer finishes editing the
         owned Worktree.
      3. **Deterministic checks** — the Ticket's required automated checks
         run against the Diff produced in the owned Worktree.
      4. **Independent QA** — `qa` stage event(s) evaluating the Ticket
         contract, complete Diff, changed files, and check evidence.
- [ ] Confirm the Run's own Worktree, branch, and base commit SHA appear
      before background work begins (visible in the Run summary line and/or
      early Timeline events), and that the Worktree path is not the primary
      repository checkout.
- [ ] Use `Reveal worktree path` to copy the active Worktree path if you want
      to inspect it directly on disk while the Run proceeds.

## After Run

On a successful Run, confirm all four of the following:

- [ ] **`COMPLETED`** — the Run status badge at the top of the Timeline reads
      `COMPLETED`. (Internally the Run's terminal state is recorded as
      `PASS`; the Web UI displays `PASS` as `COMPLETED`.)
- [ ] **The local commit** — a `commit` stage event with status `COMPLETED`
      and event type `commit_recorded` is present, with a commit SHA,
      branch, and changed-files list in its details. Verify independently
      with `git log` in the repository (not the Worktree) that a new commit
      exists on the Run's feature branch and that its message contains the
      Ticket identifier. No push, Pull Request, or merge should have
      occurred — the Controller only ever creates a local commit.
- [ ] **Retained events** — the full event stream remains visible in the
      Timeline (and on disk at
      `<repository>/.ticket-autopilot/runs/<run_id>/events.jsonl`) after the
      Run finishes and after reloading the page. Events are append-only and
      are never rewritten.
- [ ] **Retained worktree** — the Run's owned Worktree directory still exists
      on disk after the Run completes; the Web UI does not delete it
      automatically. Confirm its path (via `Reveal worktree path` or the Run
      summary) still resolves to a real directory.

## Failure Handling

A Run does not always end in `COMPLETED`. When it does not, inspect the
stated evidence for the actual terminal state and report exactly what that
evidence shows. Never describe `BLOCKED`, `HARD_BREAK`, or `QA_EXHAUSTED` as
`PASS`, and never relabel any pending or failed state as `PASS` — only a
schema-valid QA PASS event followed by a recorded commit is `COMPLETED`.

- **`BLOCKED`** — The Run status badge shows `BLOCKED` (highlighted as an
  error state). Inspect the corresponding Timeline event's `reason` field
  and `details` (for example missing/empty Diff, unsafe changed paths, or a
  QA verdict of `BLOCKED`). `BLOCKED_NEEDS_HUMAN` and `TECHNICAL_BLOCKED` are
  related sub-reasons surfaced the same way — read the specific reason text
  rather than assuming a generic block. No commit is recorded in this state.
- **`HARD_BREAK`** — The Run status badge shows `HARD_BREAK`, and the
  Timeline additionally renders a dedicated "Hard Break — human intervention
  required" panel. Inspect its `Role`, `Stage`, `Round`, `Reason`,
  `Worktree`, and `Allowed actions` fields — these identify which actor
  (Developer or QA Agent) failed, at which stage/round, why, and what the
  owner is permitted to do next (for example Retry or Stop). A Hard Break is
  never disguised as a QA FAIL; treat it as a stop signal requiring human
  review, not as a checklist failure to route around.
- **`QA_EXHAUSTED`** — The Run status badge shows `QA_EXHAUSTED`. Inspect the
  final `qa` stage event (event type `qa_attempts_exhausted`) and its
  `findings` in `details` — this is the fifth consecutive QA attempt that
  did not return PASS. Also review the earlier QA rounds in the Timeline
  (`qa_attempt` values `1..5`) to see what each round's findings were and
  what the Developer changed in response. No commit is recorded in this
  state; the Ticket needs further Developer work or owner intervention
  before it can be re-run.

For any of the three states above, also check the `Backend process output`
panel for raw Agent CLI stdout/stderr around the failure, and use `Retry
current stage` or `Stop owned Run` only as the Timeline's `Allowed actions`
or button state permit — do not start a second Run for the same repository
while this one remains active or unresolved.

# Ticket 1

## 1. Title

Recover orphaned PREPARING prompt records so Prepare never deadlocks

## 2. Goal (why)

A crashed or killed service currently leaves a `prompt-metadata.json` stuck in `PREPARING` forever, and `PromptResolver.has_active_run()` then blocks every later Prepare with `BLOCKED_REQUIREMENTS: an owned Run is already active` until a human edits JSON by hand. Prepare must stay single-flight while alive owners exist, but must self-recover from dead owners.

## 3. Scope boundary

- **In scope:**
  - `PromptResolver.prepare()` records `owner_pid` and `created_at` in each new `prompt-metadata.json`.
  - `PromptResolver.has_active_run()` treats a `PREPARING` record as orphaned when its `owner_pid` is no longer alive, or when a legacy record without `owner_pid` is older than a 30-minute stale timeout.
  - An orphaned record is finalized in place to `status: HARD_BREAK_PLANNER`, `planner_outcome: failed`, with a `hard_break_reason` naming orphan recovery; it is never deleted and never marked READY.
  - Unit tests for alive-owner blocking, dead-owner recovery, and legacy-record timeout in `tests/`.
- **Out of scope (explicit non-goals):**
  - No changes to `WebAgentLoop` or `state.json` ACTIVE-state handling.
  - No changes to `ticket_controller` lifecycle records or exit codes.
  - No UI changes and no new HTTP endpoints.
  - No third-party dependencies.

## 4. Acceptance criteria

- [ ] AC-1: Given a `PREPARING` record whose `owner_pid` is not alive, when `has_active_run()` is called, then it returns False and the record file now reads `HARD_BREAK_PLANNER` with `planner_outcome: failed` and a non-empty `hard_break_reason`.
- [ ] AC-2: Given a `PREPARING` record whose `owner_pid` is alive, when `has_active_run()` is called, then it returns True and the record is unchanged (single-flight preserved).
- [ ] AC-3: Given a legacy `PREPARING` record without `owner_pid` whose file mtime is older than 30 minutes, when `has_active_run()` is called, then it is recovered as in AC-1; a younger legacy record still blocks.
- [ ] AC-4: Given a fresh `prepare()` call, when its `prompt-metadata.json` is written, then it contains the caller's `owner_pid` and an ISO-8601 `created_at`.
- [ ] AC-5: Given any orphan recovery, when the record is finalized, then the original `issue_key` and prior fields are retained and no `prompt-metadata.json` is deleted.

## 5. Verification method (the deterministic gate)

- Type: command
- Command or procedure: `python3 -m pytest tests/ -q`
- Pass: full suite green including the new orphan-recovery tests; exit code 0.
- Fail: any red test enters the bounded fix loop (max 5 QA rounds), then HARD_BREAK.

## 6. Dependencies

- None. The defect record from 2026-07-31 (run `aio-021-prompt-20260731080659928309-6b30c8`, manually finalized) documents the failure mode.

## 7. Definition of Done

- [ ] Acceptance criteria met
- [ ] Verification method passes
- [ ] No new lint/type errors
- [ ] A short note in `src/ticket_autopilot/engine/README.md` or module docstring documents the orphan-recovery rule

## 8. Risk & rollback

- Risk: PID reuse could mistake a fresh unrelated process for the owner and keep blocking; mitigated by combining the liveness check with the 30-minute stale timeout as an upper bound. Recovery marking a still-live prepare as failed is prevented by checking liveness before the timeout.
- Rollback: single `git revert` of the PR; recovered metadata files keep their evidence and need no migration.

## 9. Human touchpoints

- Trigger: repository owner moves the issue to In Progress.
- Gate: repository owner reviews and merges the PR.
- Owner authority: the owner may create a Draft PR while QA is pending and may explicitly authorize merge; all overrides retain original evidence with actor/action/time/reason.
- Override policy: `QA_PENDING` and `HUMAN_VISUAL_REVIEW_PENDING` may accompany a Draft PR; a failed verification is never reported as PASS.
- Escalation: after 5 failed QA fix rounds, report HARD_BREAK with the failing evidence.

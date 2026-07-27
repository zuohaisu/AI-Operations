# AI-Operations — Project Memory

## What this project is
Conceptually **Ticket Autopilot** — a lightweight local controller that turns a structured ticket into a verified, independently QA'd GitHub PR (spec: `specs/Ticket Autopilot v0.1 Specification.md`). Git repo folder temporarily stays `AI-Operations`. North Star per `AGENTS.md`: ticket-driven automated software delivery. Start with a reuse-first capability audit + one low-risk vertical slice (no custom platform).
- Team name is **VF/VFF** but is intentionally NOT used in this project (hard to pronounce).

## Plane project (task tracking)
- Workspace `hspace` (Plane Cloud), project **Ticket Autopilot / AIO**, ID `d40168f5-5d44-4810-a39e-3b6558e9bf6e`.
- URL: https://app.plane.so/hspace/projects/d40168f5-5d44-4810-a39e-3b6558e9bf6e/
- The Plane MCP **cannot create projects** — use the REST API. Full how-to + gotchas are in the daily log (2026-07-27.md). Key ones: create cycle needs `project_id` in body; work-item create ignores `state_id`/`label_ids`/`cycle_id` (set via PATCH with `state`/`labels`, and cycle via `POST /cycles/{cid}/cycle-issues/` `{"issues":[id]}`).

## Directory structure (scaffolded 2026-07-27, restructured Option B same day)
- `src/ticket_autopilot/` — tool package: `cli.py` (argparse stub), `controller.py`/`config.py`/`models.py` (TBD), `adapters/` (linear/github/git/claude/codex), `services/` (validators/managers), `schemas/` (ticket-spec + qa-verdict JSON Schemas).
- `tests/` — unit / integration / fixtures.
- `tooling/vivarium-forge-flow/` — **the engine**; `ticket-pipeline/` is now a SUBDIRECTORY inside it (Option B: ticket-pipeline is part of Ticket Autopilot, not a peer). `close_ticket.py` imports `ticket-pipeline/plane_client.py` via relative `../../ticket-pipeline` — still resolves correctly after the move, zero code change. Internal package name `vff/` and dir name `vivarium-forge-flow/` kept for now (code-level rename pending user request).
- Kept untouched: `specs/`, `research/`, `tooling/start-prompt/` (parked), `tooling/codex-notification-setup/` (parked), `logs/`, `tasks/` (Chinese task list), `AGENTS.md`, `IDEA.md`.
- `pyproject.toml` (src-layout, console script `ticket-controller`), `.gitignore` extended (`.ticket-autopilot/`, `runs/`, `worktrees/`, `.env`).

## Future plan: open-source Ticket Autopilot as its own GitHub repo
- When open-sourced later, re-publish `tooling/vivarium-forge-flow/` (the engine + ticket-pipeline) as a standalone **Ticket Autopilot** GitHub repo, separate from this `AI-Operations` meta-repo.
- Implication for now: keep `vivarium-forge-flow/` self-contained (its own `README`, tests, `.gitignore`) so it can be lifted out cleanly later.

## Conventions / preferences
- Reply in Chinese for this user; git write ops need explicit approval.
- Goal-drift log + mandatory [Goal check] line at start of each piece of work (see AGENTS.md).

# AI-Operations — Project Memory

## What this project is
Conceptually **Ticket Autopilot** — a lightweight local controller that turns a structured ticket into a verified, independently QA'd GitHub PR (spec: `specs/Ticket Autopilot v0.1 Specification.md`). Git repo folder temporarily stays `AI-Operations`. North Star per `AGENTS.md`: ticket-driven automated software delivery. Start with a reuse-first capability audit + one low-risk vertical slice (no custom platform).
- Team name is **VF/VFF** but is intentionally NOT used in this project (hard to pronounce).

## Plane project (task tracking)
- Workspace `hspace` (Plane Cloud), project **Ticket Autopilot / AIO**, ID `d40168f5-5d44-4810-a39e-3b6558e9bf6e`.
- URL: https://app.plane.so/hspace/projects/d40168f5-5d44-4810-a39e-3b6558e9bf6e/
- The Plane MCP **cannot create projects** — use the REST API. Full how-to + gotchas are in the daily log (2026-07-27.md). Key ones: create cycle needs `project_id` in body; work-item create ignores `state_id`/`label_ids`/`cycle_id` (set via PATCH with `state`/`labels`, and cycle via `POST /cycles/{cid}/cycle-issues/` `{"issues":[id]}`).

## Directory structure (finalized 2026-07-28)
- `src/ticket_autopilot/` — **the product package (Ticket Autopilot)**.
  - `engine/` — **Engine** (orchestration core; importable as `ticket_autopilot.engine`): `engine.py` (DAG + retry-loop interpreter), `drivers.py` (llm/cli/hermes/script executors + guardrails), `store.py` (run snapshots), `cli.py` (`python -m ticket_autopilot.engine`), `handlers/close_ticket.py` (only node touching Plane; reuses `reference/ticket-pipeline/plane_client.py`).
  - `connectors/` — **Connector layer** (glue to Linear/Plane/GitHub/Codex). Renamed from `adapters/` 2026-07-28 (user picked "Connector" over "Handler": Handler collides with engine's internal `handlers/` and is too granular).
  - `cli.py` / `schemas/` / `services/` — product CLI (`ticket-controller` entry = `ticket_autopilot.cli:main`), ticket-spec + qa-verdict JSON Schemas, validators/managers (scaffold).
  - `reference/ticket-pipeline/` — predecessor PoC (orchestrator.py, plane_client.py, dagu-poc/); reached by `close_ticket.py` via relative `../../reference/ticket-pipeline`.
  - `workflows/` — YAML defs (`ticket-pipeline.yaml`, `ticket-pipeline-hermes.yaml`).
  - `runs/` + `sandbox/` — runtime artifacts (gitignored; `sandbox/*` keep `.gitkeep`).
- `tooling/start-prompt/` — **parked** prompt-source + eval (`core/` `modules/` `platform/` `eval/`; `eval/build_v5.py` reads `core`/`modules` as siblings of `eval`).
- `tooling/codex-notification-setup/` — parked codex infra config.
- `specs/` `research/` `logs/` `tasks/` `tests/` — spec doc, research notes, goal-drift log, Chinese task list, top-level product tests.
- `pyproject.toml` (src-layout, console `ticket-controller` = `ticket_autopilot.cli:main`), `.gitignore` (`.ticket-autopilot/`, `runs/`, `worktrees/`, `sandbox/*`, `.env`).

## Naming convention (locked 2026-07-28)
- **Product** = "Ticket Autopilot"; **Engine** = the orchestration core (`src/ticket_autopilot/engine/`); **Connector** = the glue layer (`src/ticket_autopilot/connectors/`, ex-`adapters/`). Legacy "Vivarium Forge Flow" / `vff` / `forge_flow` naming fully removed from code+docs on 2026-07-28.

## Future plan: open-source Ticket Autopilot
- Product lives in `src/ticket_autopilot/`; to open-source later, publish that package (Engine + Connector + reference) as a standalone GitHub repo, separate from this `AI-Operations` meta-repo.

## Conventions / preferences
- Reply in Chinese for this user; git write ops need explicit approval.
- Goal-drift log + mandatory [Goal check] line at start of each piece of work (see AGENTS.md).

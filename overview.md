# Overview — Ticket Autopilot PRD

## What was done
Wrote the product-level PRD for **Ticket Autopilot** at `specs/Ticket Autopilot PRD.md`.

## Key decisions
- **Grounded in the product actually built, not the stale spec.** The old `v0.1 Specification.md` describes Linear + Claude Code + Codex + a `ticket_controller` package — that architecture is explicitly STALE. The PRD reflects the real product: **Plane + declarative Engine (YAML→DAG) + Connectors (plane/github/qa) + Drivers + Guardrails**, in `src/ticket_autopilot/`.
- A dedicated **§0 divergence table** documents exactly where the new PRD departs from the v0.1 spec, so future readers (and open-source users) aren't misled.
- Followed the feature-spec template: Problem → Goals → Non-Goals → Personas/Stories → Closed-loop workflow → Architecture → Two contracts → Guardrails → P0/P1/P2 requirements → Metrics (North Star + drivers + health) → Risks → Open Questions → Phasing/DoD.

## Notable calls the PM should confirm
- **Retry limit**: Engine default `max_retries=5` vs old spec's "2 fixes / 3 QA". Flagged as Open Question Q1 (configurable, default needs locking).
- **Non-goals kept strict**: no Web UI in v0.1 (NG1), no auto-merge, no resume, reuse-first — per AGENTS.md red lines.
- **Open items surfaced**: pi identity (Q2), QoderWake CLI as 2nd QA (Q3), product-level CLI stub (Q4), read-only dashboard vs QoderWake UI (Q5).

## Deliverable
- `specs/Ticket Autopilot PRD.md` — the PRD (authoritative going forward; old spec should be archived).

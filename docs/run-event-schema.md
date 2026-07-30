# Run event schema v1.0

`<repository>/.ticket-autopilot/runs/<run_id>/events.jsonl` is the append-only
source for a Web Run Timeline. `state.json` and
`web-agent-loop-state-v1.json` are recoverable snapshots only; readers must not
invent Timeline facts from either snapshot.

Each newline is one JSON object with:

- `schema_version: "1.0"`, positive monotonic `sequence`, UTC `timestamp`, and `run_id`;
- `stage`, `role`, non-negative `round`, `status`, `event_type`, and `actor_type`;
- relative `artifact_refs` and object `details`.

`RunEventStore` rejects malformed or non-monotonic streams. It recursively
masks credential-named fields, known local configuration values, and recognised
token patterns before append. `RunManager` emits Run creation/state events;
`WebAgentLoop` emits planner prompt provenance, Developer/check/QA/Commit,
Hard Break, retry/stop, delivery-gate, and repository-owner audit events.
`TicketBoard` returns the exact stream at `GET /api/runs/<run_id>` and the UI
renders those objects with `textContent` only.

The authoritative delivery states are retained as independent events:
`QA_PENDING`, `HUMAN_VISUAL_REVIEW_PENDING`, `READY_FOR_REVIEW`,
`DIFF_SPLIT_REQUIRED`, `USER_OVERRIDE_APPROVED`,
`MERGE_AUTHORIZED_BY_USER`, and `TECHNICAL_BLOCKED`. An owner action has a
separate audit event (`actor`, `action`, `approved_at`, `reason`); it never
rewrites a deterministic, QA, or visual verdict event.

Changing this schema requires synchronized updates to `run_events.py`,
`RunManager` producers, `WebAgentLoop` producers, `TicketBoard` readers,
`static/app.js`, and `tests/test_web_run_tracking.py` plus
`tests/integration/test_web_hard_break.py`.

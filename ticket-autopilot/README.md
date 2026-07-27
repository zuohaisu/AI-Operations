# Ticket Autopilot

> A tiny, agent-native workflow engine for **ticket-driven automated software delivery**.
> Declarative YAML in → a runnable state machine that drives your agents (LLM / CLI / script)
> through a Plan → Execute → Verify → Close loop, with a native **verify-reject →
> re-execute retry loop** and **strict CLI guardrails**.

`vff` is the internal package / CLI name (historic; migration to `ticket_autopilot` pending).

---

## Why this exists

We already have `ticket-pipeline/orchestrator.py` doing this for one
hard-coded pipeline. Ticket Autopilot generalizes that pattern: the same engine runs any
workflow you describe in YAML. The two things that made our pipeline special —
the **verify→reject→execute loop** and the **strict execution sandbox** — are
first-class here, not afterthoughts.

## Layout

```
vivarium-forge-flow/           (or: ticket-autopilot/)
├── ticket-pipeline/            # reference implementation + Plane client
│   ├── orchestrator.py
│   ├── plane_client.py
│   ├── dagu-poc/
│   └── DAGU_VS_ORCHESTRATOR.md
├── vff/                        # engine core (package)
│   ├── __init__.py
│   ├── __main__.py             # `python -m vff`
│   ├── engine.py               # DAG + retry-loop interpreter (the brain)
│   ├── drivers.py              # llm / cli / hermes / script executors (+ guardrails)
│   ├── store.py                # run snapshots (runs/*.json)
│   ├── cli.py                  # run / runs commands
│   └── handlers/
│       └── close_ticket.py     # the only node that touches Plane (reuses plane_client)
├── workflows/
│   ├── ticket-pipeline.yaml          # reference: llm/cli/script drivers
│   └── ticket-pipeline-hermes.yaml   # Hermes-as-driver variant
├── tests/test_engine.py       # unittest: loop + guardrails
├── runs/                      # snapshots (gitignored)
└── sandbox/                   # strict cwd for the cli executor (gitignored)
```

## Run it

Headless self-test (no LLM/CLI/Plane keys needed — uses `mock` drivers):

```bash
PYTHONPATH=. python -m vff run workflows/ticket-pipeline.yaml \
    --mock --params '{"ticket_id":"DEMO-1"}'
```

Real run (needs `XY_LLM_*` env for the planner/verifier, and a `claude` CLI
on PATH for the executor; the closer writes to Plane via `plane_client`):

```bash
export XY_LLM_BASE_URL=...   # e.g. https://api.deepseek.com
export XY_LLM_API_KEY=...
export XY_LLM_MODEL=...      # e.g. deepseek-chat
PYTHONPATH=. python -m vff run workflows/ticket-pipeline.yaml \
    --params '{"ticket_id":"<real-plane-uuid>"}'
```

List snapshots: `PYTHONPATH=. python -m vff runs`

## Minimal YAML schema

```yaml
version: "1.0"
name: ticket-pipeline
vars:
  max_retries: 5            # QA retry cap (user: real manual max seen = 7; use 5)

agents:                     # persona / driver registry
  planner:
    driver: llm
    system: "You are the Planner..."
  executor:
    driver: cli
    command: claude
    cwd: ./sandbox           # strict: designated directory
    permission_mode: read-only
    tools: [Read, Glob, Grep]  # allowlist — no write tools
    system: "You are the Executor..."
  verifier:
    driver: llm
    expect: json             # parse output as JSON
    system: "Reply ONLY JSON {decision:accept|reject, reason:...}"
  closer:
    driver: script
    entry: close_ticket      # handlers/close_ticket.py

params:
  ticket_id: {type: string, description: Plane ticket UUID}

nodes:
  - id: plan
    agent: planner
    capture: plan             # store output under this key
    inputs: {ticket_id: ${params.ticket_id}}
  - id: execute
    agent: executor
    capture: result
    inputs: {plan: ${nodes.plan}}
  # ... verify, close ...

edges:
  - {from: plan, to: execute}                 # forward (defines `needs`)
  - {from: execute, to: verify}
  - from: verify
    to: execute
    kind: loop                                # retry back-edge (NOT a `needs`)
    when: "nodes.verify.decision == 'reject'"  # python expr over ctx
    max_retries: ${vars.max_retries}
  - from: verify
    to: close
    when: "nodes.verify.decision == 'accept'" # conditional forward
```

### Field reference

| Key | Meaning |
|---|---|
| `vars` | reusable constants, referenced as `${vars.x}` |
| `agents.<name>.driver` | `llm` \| `cli` \| `hermes` \| `script` \| (mock, CLI-only flag) |
| `agents.<name>.system` | system prompt for llm/cli |
| `agents.<name>.expect` | `json` → parse agent output as JSON (verifier) |
| `agents.<name>.cwd` / `tools` / `permission_mode` | **cli guardrails** (see below) |
| `agents.<name>.entry` | `script` driver → `handlers/<entry>.py:<entry>` |
| `nodes[].capture` | key under which the node's output is stored |
| `nodes[].inputs` | `${nodes.x}` / `${params.x}` / `${vars.x}` templating |
| `edges[]` (forward, no `when`) | defines `needs` (ordering) + always fires |
| `edges[]` with `when` | conditional trigger; fires only if expr true |
| `edges[]` with `kind: loop` | retry back-edge; carries `when` + `max_retries` |

`when` / `${...}` are Python expressions over the run context:
`nodes.<id>` (captured output; dict → attribute access),
`params`, `vars`, `retry` (per-edge retry count).

## CLI guardrails (strict by default — per user decision)

The `cli` driver spawns an external CLI (default `claude`) inside a **strict
sandbox**:

- **cwd restriction** — `cwd` must resolve *inside* an allowed root
  (`sandbox/` by default). Attempting to point it outside raises
  `SecurityError` before anything spawns. See `tests/test_engine.py`
  (`test_cwd_outside_allowed_root_is_rejected`).
- **tools allowlist** — passed via `--allowedTools` (e.g. `Read,Glob,Grep`).
- **read-only** — `--permission-mode read-only` by default.

To relax later (user: "you open it up afterwards"), widen `tools`, set
`permission_mode: default`, or expand `allowed_roots` in `drivers.py`.

## Hermes as the execution backend (compose, don't rewrite)

Instead of a bare LLM or the `claude` CLI, a node can run as a **full Hermes
sub-agent** by setting `driver: hermes`. Ticket Autopilot keeps owning the *control flow*
(deterministic loop, `max_retries` cap, snapshot, strict guardrails); Hermes
owns *execution* — its tools, skills, and `delegate_task` sub-agents. See
`workflows/ticket-pipeline-hermes.yaml` (same loop, three reasoning nodes use
`driver: hermes`).

How it connects: `drivers.hermes_call` POSTs the node's prompt to the **Hermes
gateway's OpenAI-compatible API** (aiohttp, default `http://localhost:8642/v1`):

```bash
export HERMES_API_URL=http://localhost:8642/v1   # default if unset
export HERMES_API_KEY=...                        # optional (gateway may require it)
export HERMES_MODEL=hermes-agent                 # default if unset
PYTHONPATH=. python -m vff run workflows/ticket-pipeline-hermes.yaml \
    --params '{"ticket_id":"<real-plane-uuid>"}'
```

- Endpoint used: `POST /v1/chat/completions` (OpenAI format; returns the
  agent's text synchronously). `expect: json` agents parse the reply as JSON.
- Optional `agent.session_key` (or `HERMES_SESSION_KEY`) → `X-Hermes-Session-Key`
  for session-scoped memory.
- The async `POST /v1/runs` + `/approval` surface (run gating) is the future
  path when a Hermes sub-agent needs a human-approval step of its own.
- Auth header is `Authorization: Bearer $HERMES_API_KEY`; adjust in
  `drivers.hermes_call` if your gateway expects a different scheme.

See `ticket-pipeline/DAGU_VS_ORCHESTRATOR.md` and the project memory
note on *Ticket Autopilot engine + Hermes-as-driver* for the rationale (Hermes gives
sub-agent orchestration + triggers; Ticket Autopilot gives the deterministic closed loop
neither off-the-shelf engine provides).

## Retry / QA policy

`vars.max_retries: 5`. Rationale from the user: manual QA has hit **7** retries
at most, but **1–2** usually suffice — 5 is the comfortable default. The loop
edge fires until `accept` or the cap is hit.

## Tests

```bash
PYTHONPATH=. python -m unittest tests.test_engine -v
```

Covers: the retry loop (verifier rejects twice → 3 executes, close only on
accept) and the CLI cwd guardrail.

## Status / next steps

- ✅ Engine (DAG + retry loop + snapshots), drivers (llm/cli/**hermes**/script/mock),
  guardrails, two workflows (reference + Hermes-as-driver), headless self-test
  (**7 tests**: loop, guardrails, Hermes dispatch + mock run).
- ⏳ Real run still needs either (a) `XY_LLM_*` keys + `claude` CLI for the
  llm/cli drivers, or (b) a running Hermes gateway (`HERMES_API_URL`/`_KEY`) for
  the hermes driver — against a live ticket.
- ⏳ Trigger and a web UI are out of scope for v0.1 — the engine is the
  reusable core. **The trigger is a pluggable adapter owned by whichever
  ticket system holds the tickets** (Plane now, Multica / Linear / GitHub
  Issues later); the engine only consumes a `ticket_id`, so swapping the
  ticket source never touches the engine. The Plane binding is localized to
  `close_ticket` (and a future trigger adapter), not baked into the core.
  Cf. the Dagu comparison in `ticket-pipeline/DAGU_VS_ORCHESTRATOR.md`.

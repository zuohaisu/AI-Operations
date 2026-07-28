## Imported Claude Cowork project instructions

This project is to upgrade the AI operating system.

# Project North Star and Drift Guard

This repository's current North Star is **ticket-driven automated software delivery**.

The minimum unit of work is one Linear or Plane ticket. The intended closed loop is:

```text
Ticket -> Development -> Deterministic Verification -> Independent QA
       -> Bounded Fix Loop -> Pull Request -> Ticket Status Update
```

The authoritative project framing is in `IDEA.md`. The authoritative operational
closed-loop workflow definition is `docs/closed-loop-workflow.md`. The current fallback
design is in `specs/Ticket Autopilot v0.1 Specification.md`. Goal-drift incidents are
recorded in `logs/goal-drift.md`.

## Mandatory Alignment Check

Before starting research, planning, or implementation, emit one concise line in the
working update:

```text
[Goal check] This work advances <closed-loop stage> by <measurable evidence>.
```

If that sentence cannot be completed concretely, do not start the work. Classify it
as a side track and ask the user whether to change priorities.

Repeat the check whenever the deliverable type changes, a new subsystem is proposed,
or the work expands beyond the active ticket. At completion, report which closed-loop
stage advanced and what evidence now exists.

## Architecture Order

Use this order and do not skip directly to a custom platform:

1. Reuse existing Linear or Plane automation, agent hooks, MCP capabilities, GitHub
   Actions, and native GitHub integrations.
2. Add the smallest deterministic glue needed to connect proven gaps.
3. Build a minimal controller only where a documented capability gap prevents the
   ticket loop from closing.

Every custom component must therefore name the existing capability that was checked
and the gap it fills.

## Current Focus

The Start Prompt research and comparison tooling is a parked supporting track. Do not
extend, benchmark, or generalize it unless the user explicitly requests that work and
its contribution to the ticket loop is stated first.

The next core milestone is not another prompt artifact. It is a reuse-first capability
audit followed by one real, low-risk ticket vertical slice.

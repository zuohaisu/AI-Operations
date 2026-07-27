# AI Operations — Project Charter

## North Star

Build a system in which one Linear or Plane ticket is the minimum closed-loop unit of
software delivery.

For one structured ticket, the system should move from requirements through
development, deterministic verification, independent QA, a bounded repair loop,
Pull Request creation, and ticket status update—with evidence retained at every gate
and human review before merge.

## Preferred Approach: Reuse First

The first design question is not “what platform should we build?” It is:

> Which parts of this loop can already be closed by Linear or Plane automation,
> agent hooks, MCP, GitHub Actions, and native GitHub integrations?

Use the following decision order:

1. Configure and compose existing capabilities.
2. Add thin, deterministic glue for verified gaps.
3. Build a small custom controller only if the existing tools cannot close the loop.

A custom system is a fallback, not the default starting point.

## Product Boundary

Core work must directly advance at least one stage of this loop:

```text
Ticket intake and contract
  -> Development invocation
  -> Deterministic verification
  -> Independent QA
  -> Bounded fix loop
  -> Pull Request and CI evidence
  -> Ticket status and result
```

General AI-agent research, universal Start Prompt design, and prompt-comparison
infrastructure are supporting work. They are not the product and must not displace a
core milestone unless explicitly reprioritized.

## Current Correction — 2026-07-22

Work drifted from the ticket-driven delivery loop into building and studying a Start
Prompt comparison system. Those artifacts are preserved under `tooling/start-prompt/`
and `research/`, but that track is now parked.

Before implementing the existing Ticket Autopilot specification as written, perform a
reuse-first capability audit. The next implementation milestone is one real, low-risk
ticket vertical slice using the maximum practical amount of existing infrastructure.

## Definition of Progress

Progress is not the number of prompts, documents, agents, or framework components
created. Progress is demonstrated by evidence that one more stage of a real ticket
can run automatically and safely, or that a specific blocker to that loop has been
removed.

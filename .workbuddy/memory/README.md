# Persistent Memory Layout

This directory preserves useful context between work sessions. It supports the ticket-delivery loop; it is not a substitute for the authoritative project documents or ticket evidence.

## Files

| File | Purpose | When to write |
| --- | --- | --- |
| [`MEMORY.md`](MEMORY.md) | Long-lived, stable project context: product boundaries, architecture decisions, naming conventions, durable tool constraints, and working agreements. | Update when a decision is confirmed, a stable fact changes, or a recurring constraint would otherwise be lost between sessions. |
| `YYYY-MM-DD.md` | Dated execution log for work performed that day: ticket context, commands and outcomes, blockers, decisions, and handoff details. | Create or update during a work session when there is evidence, a decision, a blocker, or a handoff worth retaining. Use the local date in the filename. |

## Writing guidance

- Write concise, factual notes with paths, ticket keys, command results, and links to the canonical artifact when useful.
- Promote only settled, reusable context from a daily log into `MEMORY.md`; keep chronology and transient details in the dated log.
- Store acceptance and verification evidence in the ticket, PR, CI, or dedicated project artifact as appropriate. Memory may point to evidence but must not replace it.
- Follow the mandatory goal-check convention in [AGENTS.md](../../AGENTS.md) for work updates.

## Do not write

- Secrets, credentials, API tokens, personal data, or `.env` contents.
- Speculation, unverified agent claims, or decisions awaiting human confirmation.
- Large command dumps, duplicated specifications, or product source code.
- Unrelated conversation history or information outside the active project.

For repository-level navigation, see the [project README](../../README.md). For ticket contract fields, see the [agent-ready ticket template](../../specs/agent-ready-ticket-template.md).

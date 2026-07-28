# Goal Drift Log

This is an append-only record of moments when work in `AI-Operations` diverges from
the project's ticket-driven delivery North Star. Record the divergence without
erasing useful artifacts or rewriting history.

## 2026-07-22 — Ticket automation drifted into Start Prompt comparison

**Status:** Detected and corrected

### Intended outcome

The intended product was a ticket-driven automated development loop, with one Linear
or Plane ticket as the minimum unit. The preferred implementation strategy was to use
existing hooks, MCP capabilities, GitHub Actions, and platform-native automation. A
small custom system was acceptable only if those capabilities could not close the
loop.

### Observed divergence

The work increasingly treated universal Start Prompt design and Start Prompt
comparison as the center of the project. The repository gained a substantial prompt
source tree, evaluation harness, and research track, while the ticket automation
remained a specification rather than an implemented vertical slice.

### Evidence

Repository evidence at detection time:

- `specs/Ticket Autopilot v0.1 Specification.md` contained an approved 1,500+ line
  design for the ticket loop.
- `tooling/start-prompt/` contained 50 tracked files and `research/` contained four
  tracked Start Prompt research documents.
- No tracked `ticket-controller` package or application source directory existed.
- `.workbuddy/memory/2026-07-22.md` described Start Prompt construction as the project
  positioning, turning a side track into an apparent North Star.
- Root `IDEA.md` and `AGENTS.md` only described a broad AI operating-system project,
  which was too vague to reject adjacent work.

### Facts versus inference

**Facts:** The Start Prompt work was a potentially reusable supporting asset, but it
became the active product goal without an explicit priority decision and did not
produce evidence that a real ticket could move further through the delivery loop.

**Inferences:** Likely causes (not directly observed facts):

1. The project-level goal was written too broadly to distinguish core product work
   from interesting AI-agent infrastructure.
2. There was no mandatory check connecting each new deliverable to a stage of the
   ticket loop.
3. The Start Prompt problem offered fast, self-contained artifacts, while end-to-end
   automation required integration decisions and therefore created more friction.
4. The existing Controller specification made “build a system” concrete, but the
   earlier “reuse existing capabilities first” preference was not encoded as an
   implementation gate.

### Impact

- Core implementation did not advance to a real one-ticket vertical slice.
- Research and evaluation work consumed attention without validating the product's
  primary closed-loop hypothesis.
- Project memory began reinforcing the drift for subsequent AI sessions.

### Correction or explicit reprioritization

1. Restore ticket-driven automated development as the project North Star.
2. Park Start Prompt research and comparison as a supporting track; preserve its
   existing artifacts but do not extend it by default.
3. Audit existing Linear/Plane, hooks, MCP, GitHub Actions, and native GitHub
   capabilities before implementing a custom Controller.
4. Build only the smallest missing orchestration needed for one real, low-risk ticket
   to reach an evidence-backed Pull Request and ticket result.

### Guard added

- `IDEA.md` is the concise project charter and priority source.
- `AGENTS.md` requires a visible goal check before research, planning, or
  implementation and again whenever scope changes.
- The Ticket Autopilot specification is explicitly a fallback design pending a
  reuse-first capability audit.
- WorkBuddy's same-day memory now labels Start Prompt work as a research side track.

### Recovery milestone

Produce a reuse-first capability map, choose the smallest uncovered gap, and run one
real low-risk ticket through the thinnest possible end-to-end vertical slice. Success
is runtime evidence from the ticket loop, not another framework or prompt artifact.

---

## Entry template

### YYYY-MM-DD — Short description

**Status:** Detected / Corrected / Accepted reprioritization

### Intended outcome

<The ticket-loop stage and measurable outcome that work was meant to advance.>

### Observed divergence

<What work actually focused on or produced instead.>

### Evidence

<Observable repository paths, commands, timestamps, issue links, or other facts.>

### Facts versus inference

**Facts:** <Observed facts only.>

**Inferences:** <Interpretations, hypotheses, or likely causes; label uncertainty.>

### Impact

<Effect on the ticket loop, safety, schedule, or project priorities.>

### Correction or explicit reprioritization

<The corrective action, or the explicit decision approving a priority change.>

### Guard added

<The concrete rule, gate, or check that prevents recurrence.>

### Recovery milestone

<The evidence-backed ticket-loop outcome that demonstrates recovery.>

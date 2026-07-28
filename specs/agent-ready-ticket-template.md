# Agent-Ready Ticket Template

> **Format alignment:** this template aligns with the senior-project-manager ticket format: the nine required fields are Title, Goal, Scope boundary, Acceptance criteria, Verification method, Dependencies, Definition of Done, Risk & rollback, and Human touchpoints.
>
> Purpose: a ticket an AI agent can pick up and execute autonomously the moment it is moved to **In Progress**. Product discussion's real deliverable is a backlog of these — not vague titles.
> Fits the closed loop: Ticket → Dev → Deterministic Verification → Independent QA → Bounded Fix → PR → Status Update.
>
> **Single authority:** this is the repository's only authoritative agent-ready ticket template. Reuse and tighten this format; do not create a competing template or ticket schema.

For branch, PR, review, and status conventions, see [CONTRIBUTING.md](../CONTRIBUTING.md). For the authoritative operational stages and evidence gates, see [the closed-loop workflow](../docs/closed-loop-workflow.md).

## How to use
- One ticket = one independently shippable unit. If it needs 5 human decisions mid-way, split it.
- Fill **every Required field**. A ticket missing Verification or Scope Boundary must not be moved to In Progress.
- Keep it boring and explicit. Agents fail on ambiguity, not on difficulty.

## 工单组拆分规则

Keep one Plane issue when the spec has one independently shippable outcome, one verification gate, and no separately releasable dependency. Split it into an issue group when any of the following is true:

- It contains two or more independently shippable outcomes, each of which can have its own acceptance criteria and deterministic verification.
- One change is a prerequisite for another, so the dependent work cannot start or be verified without the prerequisite.
- The outcomes have different owners, risk/rollback paths, or human gates that would make one nine-field contract ambiguous.

Create the prerequisite issue first; make each dependent issue name and link its prerequisite in **Dependencies**. Do not use a parent issue to hide incomplete fields: every child is a complete nine-field contract, has its own non-empty Out of scope list, and can be independently moved to In Progress. Keep shared rationale in the source spec and link it rather than duplicating mutable material.

## 防范围蔓延核对清单（hard gate）

Before a draft becomes a Plane issue, all checks below must pass:

- [ ] **Out of scope** exists and contains at least one concrete non-goal; “TBD”, “N/A”, and empty lists fail.
- [ ] Every Acceptance criterion is a pass/fail statement, written as Given/When/Then or with an equally objective observable result.
- [ ] **Verification method** contains an exact, mechanically runnable command or a concrete deterministic inspection procedure wherever a command is not possible.
- [ ] The work changes only the stated In scope items; new ideas become a new spec or linked ticket, never an implicit addition.

## In Progress contract gate

A PM, automation, or reviewer must keep a ticket in planning/Backlog when any of the nine required fields is absent or placeholder-only, when Scope boundary or Verification method is missing, or when the hard-gate checklist fails. Such a ticket is **not eligible for In Progress**; report it as `BLOCKED_NEEDS_HUMAN` rather than guessing or starting partial work.

## Required fields

### 1. Title
Imperative, single outcome. e.g. `Add rate-limit header to /login endpoint`.

### 2. Goal (why)
1–2 sentences of human intent. Why this matters, what changes for the user.

### 3. Scope boundary
- **In scope:** concrete list
- **Out of scope (explicit non-goals):** list what the agent must NOT touch — this is the anti-scope-creep guard

### 4. Acceptance criteria
Testable checklist. Each line is pass/fail.
- [ ] Given …, when …, then …
- [ ] …

### 5. Verification method (the deterministic gate)
How we know it passed, machine-checkable when possible.
- Command: `pytest tests/test_x.py` / `npm run build` / specific script
- Or a QA script run by the QA agent
- Pass = all green; Fail = agent enters the bounded fix loop

### 6. Dependencies
- Blocking tickets / PRs / env vars / running services
- If a dependency is unmet, the agent should not start (or should report, not guess)

### 7. Definition of Done
Explicit list that, when all true, triggers PR + status update:
- [ ] Acceptance criteria met
- [ ] Verification method passes
- [ ] No new lint/type errors
- [ ] Docs/comments updated if needed

### 8. Risk & rollback
- What could break
- How to revert (feature flag, git revert, downgrade)

### 9. Human touchpoints
- **Trigger:** who moves to In Progress (the only required human action to start)
- **Gate:** who reviews/merges the PR
- **Escalation:** after N failed fix loops, escalate to human with context

## Optional fields
- **Agent budget:** max fix loops before escalation (default 3)
- **Pointers:** key files / functions to start from
- **Reference:** related spec, doc, or past ticket

## Mapping to Linear / Plane
- **Title** → ticket title
- **Goal / Scope / AC / Verification** → ticket description (use the sections above)
- **Status = In Progress** → triggers the autonomous loop
- **Definition of Done met + PR** → Controller moves ticket to In Review when its evidence gates are met; human reviews and merges

## 空白可填模板

Copy this block into a planning document or the Plane issue description. Replace every placeholder before moving the issue to **In Progress**.

```md
## 1. Title
<Imperative, single outcome>

## 2. Goal (why)
<1–2 sentences describing the intended outcome and value>

## 3. Scope boundary
- **In scope:**
  - <included change>
- **Out of scope (explicit non-goals):**
  - <excluded change>

## 4. Acceptance criteria
- [ ] <Testable pass/fail condition>

## 5. Verification method (the deterministic gate)
- Type: <command / inspection / QA script>
- Command or procedure: `<exact command or steps>`
- Pass: <objective passing result>
- Fail: <bounded fix-loop or blocked outcome>

## 6. Dependencies
- <ticket / service / environment variable / none>

## 7. Definition of Done
- [ ] Acceptance criteria met
- [ ] Verification method passes
- [ ] <required documentation, QA, or CI evidence>

## 8. Risk & rollback
- Risk: <what could break>
- Rollback: <how to safely revert>

## 9. Human touchpoints
- Trigger: <who or what moves the issue to In Progress>
- Gate: <human reviewer/merger>
- Escalation: <when to report BLOCKED_NEEDS_HUMAN>
```

## Spec → Plane issue 操作流程

1. Draft the ticket from the **空白可填模板** and complete all nine required fields.
2. Check that Scope boundary, Acceptance criteria, Verification method, Dependencies, Risk & rollback, and Human touchpoints are concrete; otherwise keep the spec in planning and resolve the gap.
3. Apply the **工单组拆分规则**. Produce one complete nine-field draft per independently shippable unit and record prerequisite links in Dependencies.
4. Run the project `spec-to-plane-issue` skill in its default dry-run mode (or its offline validator). Any failed hard-gate check is `BLOCKED_NEEDS_HUMAN`; do not create a partial issue.
5. Create one Plane issue per passing draft with the Title as its title and the completed nine-field template as its description. Add the relevant project, priority, labels, and dependency links. Plane writes require an explicit apply action and human confirmation.
6. Re-read each Plane description against the source spec. The Plane issue becomes the execution contract; link the source spec rather than duplicating changing material.
7. A PM or designated human moves only a complete issue to **In Progress**. The development agent follows the contract and records evidence.
8. After the Definition of Done and required evidence gates are met, the Controller or human prepares the PR using the [PR template](../.github/PULL_REQUEST_TEMPLATE.md) and moves the issue to **In Review**. Failed evidence or an unresolved ambiguity maps to **Blocked** / `BLOCKED_NEEDS_HUMAN` as described in [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Worked example (low-risk vertical slice)

**Title:** Add a `GET /health` endpoint that returns service status

**Goal:** Ops can ping service liveness without auth; supports the future agent-driven deploy loop.

**Scope boundary**
- In scope: new endpoint, JSON `{"status":"ok"}`, wired into router, one test
- Out of scope: auth, metrics, DB checks, dashboard

**Acceptance criteria**
- [ ] `GET /health` returns 200 with `{"status":"ok"}`
- [ ] Unknown routes still return 404 (no regression)
- [ ] Test covers both

**Verification method**
- Command: `pytest tests/test_health.py`
- Pass = test green

**Dependencies:** none

**Definition of Done**
- [ ] Criteria met
- [ ] `pytest` green
- [ ] No new lint errors

**Risk & rollback:** trivial; revert PR if needed.

**Human touchpoints**
- Trigger: PM moves ticket to In Progress
- Gate: PM reviews & merges PR
- Escalation: after 3 failed fix loops, ping PM in chat

**Agent budget:** 3

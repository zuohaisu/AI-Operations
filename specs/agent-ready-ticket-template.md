# Agent-Ready Ticket Template

> Purpose: a ticket an AI agent can pick up and execute autonomously the moment it is moved to **In Progress**. Product discussion's real deliverable is a backlog of these — not vague titles.
> Fits the closed loop: Ticket → Dev → Deterministic Verification → Independent QA → Bounded Fix → PR → Status Update.

## How to use
- One ticket = one independently shippable unit. If it needs 5 human decisions mid-way, split it.
- Fill **every Required field**. A ticket missing Verification or Scope Boundary must not be moved to In Progress.
- Keep it boring and explicit. Agents fail on ambiguity, not on difficulty.

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
- **Definition of Done met + PR** → agent moves ticket to In Review / Done; human merges

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

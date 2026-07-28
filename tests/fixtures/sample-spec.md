# Sample specification: offline ticket-contract evidence

## 1. Title
Validate a spec-to-Plane issue draft offline

## 2. Goal (why)
PMs can prove that a proposed Plane issue is a complete execution contract before any external write occurs.

## 3. Scope boundary
- **In scope:**
  - Validate the existing nine-field Markdown contract and render a normalized preview.
- **Out of scope (explicit non-goals):**
  - Creating a Plane work item or changing a Plane project.

## 4. Acceptance criteria
- [ ] Given `tests/fixtures/sample-spec.md`, when the offline validator runs, then it exits with status 0 and renders all nine fields.
- [ ] Given an incomplete Scope boundary, when the offline validator runs, then it exits non-zero with a BLOCKED error.

## 5. Verification method (the deterministic gate)
- Type: command
- Command or procedure: `python3 tooling/spec_to_issue.py --dry-run --spec tests/fixtures/sample-spec.md --assert`
- Pass: the command exits 0 and prints the nine-field draft.
- Fail: report `BLOCKED_NEEDS_HUMAN`; do not create a Plane issue.

## 6. Dependencies
- None; the validator uses only the Python standard library and the source spec.

## 7. Definition of Done
- [ ] All acceptance criteria are met.
- [ ] The deterministic verification command exits 0.
- [ ] No network request or Plane write occurs.

## 8. Risk & rollback
- Risk: a malformed planning document could be rejected before a PM can refine it.
- Rollback: revert the documentation/tooling change; no external state exists.

## 9. Human touchpoints
- Trigger: PM requests a draft from a source spec.
- Gate: PM reviews the dry-run preview before any apply action.
- Escalation: after three invalid-draft iterations, report `BLOCKED_NEEDS_HUMAN` to the PM.

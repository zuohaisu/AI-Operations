---
name: spec-to-plane-issue
description: Turn a source spec into one or more bounded, validated Plane issue drafts. Default is offline dry-run; Plane writes require explicit --apply and a human confirmation.
---

# Spec → Plane issue

Use this skill when a PM supplies a spec (a file path or pasted text) and wants a
Plane issue or issue group. It is the project-level intake mechanism; the canonical
nine-field contract remains
[`specs/agent-ready-ticket-template.md`](../../../specs/agent-ready-ticket-template.md).
Do not invent a second ticket format, controller, or Plane client.

## Inputs and outputs

- **Input:** one source spec file or pasted source-spec text. It may be prose; it
  does not need to have the nine fields already.
- **Output:** one or more Markdown drafts using all nine canonical fields. A
  multi-ticket output uses `# Ticket <n>` before each complete draft.
- **Default:** dry-run/preview only. It reads source material and writes or prints
  local Markdown only. It does not read credentials, invoke curl, or contact Plane.

## Drafting procedure

1. Read the source spec, this skill, and the canonical template. Identify the
   intended user outcome, explicit non-goals, dependencies, deterministic evidence,
   risk, and human decisions. Do not silently fill a missing fact with an assumption.
2. Apply the template's **工单组拆分规则**:
   - Keep one ticket for one independently shippable outcome with one verification
     gate.
   - Split separate shippable outcomes, prerequisite/dependent work, or work with
     different owners, risk/rollback, or human gates.
   - Put prerequisite links in every dependent ticket's **Dependencies**. Each child
     must have all nine fields; a parent cannot stand in for a missing child field.
3. Draft each candidate in the exact nine-field shape. Write a concrete non-empty
   **Out of scope (explicit non-goals)** list. Write every acceptance criterion as
   Given/When/Then or explicit pass/fail. Include an exact runnable command in
   backticks under **Verification method** whenever a command is possible.
4. Save the draft(s) locally or pass the content to the offline validator:

   ```bash
   python3 tooling/spec_to_issue.py --dry-run --spec <drafts.md> --assert
   ```

   The validator emits normalized Markdown only on success. If it exits non-zero,
   surface its `BLOCKED` error, repair only with source-spec evidence or ask the PM,
   and do **not** produce a partial Plane issue.
5. Return the validated Markdown preview and the source-spec link. State whether it
   is a single issue or an ordered issue group and list dependency edges. A passing
   draft is eligible for PM review, not automatically In Progress.

## Hard contract gate

Do not advance a draft to Plane or In Progress when any of these is true:

- A required field is absent, empty, or placeholder-only.
- Scope boundary lacks a concrete, non-empty Out of scope list.
- An acceptance criterion is not objectively pass/fail.
- Verification lacks an exact runnable command (or a concrete deterministic
  procedure when no command can exist).

Report `BLOCKED_NEEDS_HUMAN` with the field and missing decision. Never guess a
scope boundary, acceptance result, dependency, or verification command.

## Plane REST apply protocol (only after `--apply` + human confirmation)

`--apply` is an explicit skill-mode request, **not** the offline validator flag.
Before any network request, show the final validated drafts and ask the PM to reply
with an unambiguous confirmation such as `APPLY_PLANE_ISSUES`. If the confirmation
is absent, ambiguous, or changes the draft, stay in dry-run. Self-tests must never
enter this section.

After confirmation, read credentials only from environment variables; never print or
persist them. Use `PLANE_API_KEY` in the `X-Api-Key` header, project ID from
`PLANE_PROJECT_ID`, optional workspace context from `PLANE_WORKSPACE_SLUG`, and API
base from `PLANE_API_BASE_URL` or the default:

```text
https://api.plane.so/api/v1
```

For every issue, use this exact sequence and record only response IDs/statuses as
evidence:

1. Create the work item with `POST /projects/{pid}/work-items/`. On this create call
   only `name`, `description_html`, `priority`, and `assignees` take effect. Do **not**
   rely on `state_id`, `label_ids`, or `cycle_id` in that body: Plane silently ignores
   them.
2. If a state or labels are requested, use `PATCH /work-items/{id}/` with
   `{"state":"<state-id>","labels":["<label-id>"]}`. The field names are `state`
   and `labels`, never `state_id` or `label_ids`.
3. If a cycle is requested, use `POST /cycles/{cid}/cycle-issues/` with
   `{"issues":["<work-item-id>"]}`. Do not send `issue_ids` or `work_item_ids`.
4. Add dependency links only after all prerequisite work-item IDs are known. Re-read
   created descriptions against the validated preview. Any API error, mismatched
   response, or missing ID is `BLOCKED`; do not claim a successful issue creation.

This is deliberately a thin, human-supervised REST procedure. It does not replace or
modify `reference/ticket-pipeline/plane_client.py`, the Engine, or production code.
For a machine-readable offline inspection of the same API contract, run:

```bash
python3 tooling/spec_to_issue.py --spec tests/fixtures/sample-spec.md --show-plane-contract --output /tmp/issue-preview.md
```

## Deterministic local self-check

Run this before handing off changes to this skill or its validator:

```bash
python3 tooling/spec_to_issue.py --dry-run --spec tests/fixtures/sample-spec.md --assert
python3 -m unittest tests.unit.test_spec_to_issue -v
```

Both commands are offline. Exit code 0 is evidence that the fixture renders all nine
fields and that missing Out of scope, unmeasurable acceptance criteria, and missing
runnable verification are blocked.

# Engineering Module

## Output schema
1. FILES INSPECTED — what you actually read. If you did not read it, do not reason about it.
2. ROOT CAUSE — labeled FACT or INFERENCE (core/04 applies).
3. PROPOSED FIX — the change, and why this change and not an adjacent one.
4. BLAST RADIUS — every file/behavior affected.
5. VERIFICATION — the exact command that proves it worked.
6. RISK — what could break that the tests do not cover.

## Rules
- Read before you write. Understand the existing implementation before changing it.
- Complexity gate: multi-file changes, architecture changes, or anything security-adjacent
  -> write the plan, wait for confirmation, then execute.
- Simple task -> just do it. Do not plan a one-line fix.
- After finishing: run tests, lint, typecheck. If you cannot verify, say so explicitly
  rather than implying it works.
- core/03 failure protocol applies. Two failed attempts, stop.

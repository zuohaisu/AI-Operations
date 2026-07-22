# System / Second-Me Module

For any long-term AI system design, answer along these eight axes explicitly.
Skipping an axis requires saying why it does not apply.

1. IDENTITY      — who does this represent, and what is its optimization target
2. MEMORY        — what is remembered, what must NOT be remembered, retention period
3. RETRIEVAL     — what is fetched, when, triggered by what
4. DELEGATION    — what it may do alone, what requires a human, where the line sits
5. AUDIT         — how do I see what it did, after the fact
6. REVERSIBILITY — how do I pause, undo, or correct it
7. CONSISTENCY   — how does judgment style stay stable across sessions and versions
8. PRODUCTIZATION— what is the smallest shippable version of this

## Rules
- Distinguish rigorously: model training / prompt design / memory / retrieval /
  orchestration / workflow / human review. Most "the AI got smarter" is context
  engineering, not capability.
- Concept -> mechanism -> process -> doc -> validation. Do not stop at concept.

# Platform Delta: Chat interfaces (Claude.ai, ChatGPT, Gemini)

- No file or shell access. core/02 autonomy table is advisory only.
- Modules cannot load on demand: paste core + the ONE relevant module at session start.
- Long sessions decay compliance. If a session exceeds ~30 turns and output quality
  drifts, re-paste core. Do not re-paste the module.
- Attachments are the only context source. Never claim to have read something not attached.

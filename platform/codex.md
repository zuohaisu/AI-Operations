# Platform Delta: Codex / Cursor / IDE agents

- Store as AGENTS.md / .cursorrules. Modules go inline if the tool has no on-demand loading.
- Context window is smaller than Claude Code's. core/01 COLD orientation should read
  the tree and entry point only, not full files.
- Diff-first: propose the diff, do not apply silently.
- If the tool auto-applies edits, treat every edit as if it were in the "ask first" column
  when the file has uncommitted changes.

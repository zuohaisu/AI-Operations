# Platform Delta: Claude Code

- Store this system as CLAUDE.md (core) + .claude/skills/ (modules). Modules load on demand.
- You have real file, shell, and git access. core/02 autonomy gates are LIVE, not hypothetical.
- Long-running commands: background them. Do not block on a build.
- Subagents: use for independent parallel reads. Do not use for anything with a write gate —
  the gate must be evaluated by you, not delegated.
- core/03 failure protocol is the highest-priority rule on this platform. The dominant
  failure mode here is the fix-fail-fix-fail loop.

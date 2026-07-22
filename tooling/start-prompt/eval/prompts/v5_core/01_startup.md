# Startup

Run this test before the first action of a session. Check in order; stop at first match.

COLD  — I have not read an orientation file this session AND the task references a
        repo/project/domain I have no context on.
        -> Read: README, directory tree, entry point, and CLAUDE.md/AGENTS.md/.cursorrules
           if present. Then STOP and state your understanding in <=5 lines. Wait.

WARM  — The task references a prior decision, file, or module not present in context.
        -> Load ONLY that. Do not read adjacent files "for context."

HOT   — Everything the task references is already in context.
        -> Execute immediately. No planning preamble.

Never load broad context speculatively. If you cannot tell whether something is needed,
it is not needed yet.

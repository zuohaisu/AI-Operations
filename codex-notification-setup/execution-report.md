# Execution Report — Codex Completion Notifications in Cursor

Date: 2026-07-19
Machine: hzuo's MacBook Air, macOS 26.5.1 (Darwin 25.5.0, arm64)

## Overall Result

**PASS WITH MANUAL STEP**

The notification mechanism is installed, syntactically valid, and independently tested
end-to-end for the notification+sound part. The one remaining gap is that Codex's own hook
**trust approval** for the newly added hook has not been granted yet — that happens through
Codex's native trust UI the first time the hook is about to run, and requires the user to
approve it once. See "Manual Steps" below.

## Environment Findings

- `codex` is **not** a standalone CLI on this machine's PATH. "Codex inside Cursor" is the
  `openai.chatgpt` VS Code-family extension installed in Cursor
  (`~/.cursor/extensions/openai.chatgpt-26.715.31925-darwin-arm64`), which spawns the same
  Codex CLI binary used by the ChatGPT desktop app
  (`~/.codex/plugins/.plugin-appserver/codex`, version `0.145.0-alpha.18`).
- Verified in the extension's `out/extension.js` that it resolves `CODEX_HOME` the exact same
  way the CLI does (`process.env.CODEX_HOME`, else `$HOME/.codex`) and spawns that binary
  directly — so `~/.codex/config.toml` and `~/.codex/hooks.json` govern Codex's behavior
  identically whether it's driven from Cursor, the ChatGPT desktop app, or a terminal. This
  directly satisfies the task's "verify it actually works inside Cursor, don't assume"
  constraint.
- `~/.codex/hooks.json` already contained a **working** `Stop`-event hook (matcher `.*`)
  running `nowledge-mem-stop-save.py` to persist Codex transcripts. This is concrete, in-place
  proof that the Stop-event hook contract already fires for this user's real Codex usage.
  Its I/O contract was read from source rather than assumed:
  - Input: JSON payload on stdin (fields include `session_id`, `cwd`, `transcript_path`, etc.),
    tolerant of empty/malformed stdin.
  - Output: no required stdout schema — the hook does its work and exits. This matches the
    same hook contract shape used by Claude Code (`hooks.json` with `matcher`/`hooks[].command`
    /`type: "command"`/`timeout`/`statusMessage`).
  - This ruled out the risk of inventing an unverified hook schema.
- `config.toml` also had a native `notify = [...]` array already wired to
  `Codex Computer Use.app/.../SkyComputerUseClient "turn-ended"` — this is a ChatGPT-desktop
  -app-specific Computer Use integration, unrelated to general OS notifications, and was left
  untouched to avoid breaking existing functionality.
- `terminal-notifier` 2.0.0 is installed via Homebrew at `/opt/homebrew/bin/terminal-notifier`
  (Apple Silicon path). `/usr/local/bin/terminal-notifier` (Intel path) does not exist on this
  machine; the script checks both.
- `/System/Library/Sounds/Glass.aiff` exists.
- `codex --help` confirms hooks require **persisted hook trust** (there's a
  `--dangerously-bypass-hook-trust` flag explicitly for automation that already vets hook
  sources — not used here, since bypassing a trust/security control isn't appropriate for this
  task).

## Selected Mechanism

**Native Codex `Stop`-event lifecycle hook**, added as a second entry alongside the existing
nowledge-mem hook in `~/.codex/hooks.json`.

Reasons:
1. It's a native Codex lifecycle mechanism (highest preference per the task's own ordering),
   not a wrapper/watcher/polling hack.
2. It's proven to already work for this exact CODEX_HOME / this exact Cursor integration (the
   nowledge-mem hook is live evidence), removing the main risk called out in the task
   (assuming a standalone-CLI mechanism transfers to Cursor).
3. `Stop` fires once per completed agent turn/task — exactly the granularity requested (not
   per tool call, not per token).
4. It does not touch or risk breaking the existing nowledge-mem hook or the unrelated
   Computer-Use `notify` callback.

## Files Created

- `/Users/hzuo/.codex/hooks/codex-task-completed.sh` — notification + sound script (mode 755).
- `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/execution-report.md` (this file)
- `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/test-results.log`
- `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/rollback.md`
- `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/hooks.json.20260719-175431.bak`
- `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/config.toml.20260719-175431.bak`

## Files Modified

- `/Users/hzuo/.codex/hooks.json` — appended a new object to the `Stop` array
  (`matcher: ".*"`, running `codex-task-completed.sh`, `timeout: 10`). The pre-existing
  nowledge-mem hook entry was left byte-for-byte untouched.

## Files NOT Modified (inspected only)

- `/Users/hzuo/.codex/config.toml` — inspected for the `notify` callback and `[hooks.state]`
  trust records. Not edited: (a) the existing `notify` callback is a different, unrelated
  ChatGPT-desktop mechanism; (b) fabricating a `trusted_hash` entry to pre-approve the new hook
  was deliberately avoided, since that hash is a security control generated by Codex itself
  and guessing/forging it would undermine the purpose of hook trust approval.

## Backup Paths

- `backups/hooks.json.20260719-175431.bak`
- `backups/config.toml.20260719-175431.bak`

## Commands Executed

See `test-results.log` for the full command transcript and outputs, including:
`codex --version`, `codex doctor --all`, extension inspection (`grep CODEX_HOME`), JSON
validation, `bash -n` syntax check, direct script execution (with/without stdin), process
check, and a direct `terminal-notifier` test.

## Validation Results

- `hooks.json`: valid JSON before and after edit (`python3 -m json.tool`).
- `codex-task-completed.sh`: passes `bash -n` syntax check; executable bit set.
- `config.toml`: unchanged, so no re-validation needed (still parses per `codex doctor`, which
  reported `config.toml parse: ok`).

## Direct Test Results

- Script run with empty stdin: exit code 0.
- Script run with a simulated Codex JSON payload on stdin: exit code 0.
- `afplay` invoked asynchronously; process list confirms it ran briefly and exited — no hang,
  no blocking of the calling shell.
- Direct `terminal-notifier` invocation: exit code 0.
- No recursive invocation possible (script does not call itself or Codex).

## End-to-End Test Status

**Not fully confirmed automatically.** Codex's hook trust model persists a `trusted_hash` per
hook in `config.toml`'s `[hooks.state]` table, generated by Codex's own approval flow (there is
no documented/discoverable way to compute this hash externally, and forging it would defeat
the purpose of the trust control). This means the very first time a `Stop` event fires after
this change, Codex is expected to prompt for approval of the new hook (the same flow that
originally trusted the nowledge-mem hook). Once approved, it persists and fires silently on
every subsequent `Stop` event, in Cursor or elsewhere sharing this `CODEX_HOME`.

## Manual Steps Required

1. In Cursor, run a minimal Codex task to trigger the first `Stop` event, e.g.:
   > Check the current working directory and reply with only: Test complete.
2. If Codex shows a hook-trust/approval prompt for the new `codex-task-completed.sh` hook,
   approve it. (If nothing prompts and the notification simply fires, no action needed —
   trust may already be scoped permissively for this hooks.json path.)
3. Confirm you see a macOS banner titled "Codex" / subtitle "Cursor" / message "Task completed.
   Ready for review." and hear the Glass sound.
4. If no banner appears despite the script itself testing successfully (see test-results.log),
   check **System Settings → Notifications** for both `terminal-notifier` and `Cursor`, and
   enable "Allow Notifications" and "Banners or Alerts" (see below).
5. If changes still don't take effect, fully quit Cursor (Cmd+Q) and reopen it so its Codex
   extension process restarts and re-reads `~/.codex/hooks.json`.

### macOS Notification Permission Check

Could not be verified programmatically in this sandboxed environment (the notification
preferences plist was not directly readable). Please check manually:

`System Settings → Notifications → terminal-notifier` — Allow Notifications: On, style:
Banners or Alerts.

`System Settings → Notifications → Cursor` — Allow Notifications: On (in case any fallback
path or Cursor's own UI surfaces something related).

The `afplay` sound is independent of these notification permission settings — it will play
regardless of whether the visual banner is authorized.

## Remaining Uncertainty

- Whether Codex's trust prompt will appear automatically on next `Stop` event, or whether
  hook trust for this `hooks.json` path is already broadly granted (since the file itself
  already had one trusted hook) — this can only be observed by actually triggering a real
  Codex turn from Cursor, which requires the user's interactive session.
- Visual confirmation of the macOS banner requires the user's own eyes; command exit codes
  (0 for both `terminal-notifier` and `afplay`) are the strongest automated signal available.

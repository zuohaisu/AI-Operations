# Rollback Instructions — Codex Notification Setup

Backups are in `/Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/`:

- `hooks.json.20260719-175431.bak` — original `/Users/hzuo/.codex/hooks.json`
- `config.toml.20260719-175431.bak` — original `/Users/hzuo/.codex/config.toml` (inspected only,
  not actually modified by this task, but backed up as a precaution before inspection)

## 1. Restore the original hooks.json

```bash
cp /Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/hooks.json.20260719-175431.bak \
   /Users/hzuo/.codex/hooks.json
python3 -c "import json; json.load(open('/Users/hzuo/.codex/hooks.json')); print('valid')"
```

This removes the new `codex-task-completed.sh` Stop hook entry and restores the file to
exactly the state it was in before this task (only the pre-existing nowledge-mem Stop hook
remains).

## 2. Remove the notification script

```bash
rm /Users/hzuo/.codex/hooks/codex-task-completed.sh
```

## 3. (Not needed) config.toml

`config.toml` was not modified — no restore action required. If you want to be extra safe,
diff it against the backup:

```bash
diff /Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/config.toml.20260719-175431.bak \
     /Users/hzuo/.codex/config.toml
```

This should show no differences.

## 4. Disable without deleting (alternative to full rollback)

If you'd rather keep the script but stop it from firing, edit `/Users/hzuo/.codex/hooks.json`
and delete just the second object in the `Stop` array (the one whose `command` points to
`codex-task-completed.sh`), leaving the original nowledge-mem hook entry untouched. Validate
with the JSON check above afterward.

## 5. Revoke hook trust (if you approved it via Codex's trust prompt)

If you approved the new hook when Codex's native trust prompt appeared, Codex will have
written a `[hooks.state."/Users/hzuo/.codex/hooks.json:stop:1:0"]` (or similar) block into
`config.toml`. After restoring `hooks.json` per step 1, that stale trust entry is harmless
(it no longer matches any hook definition) but can be removed manually by deleting that
`[hooks.state."..."]` block from `/Users/hzuo/.codex/config.toml` if you want a fully clean
file.

## 6. Full manual revert to pre-task state

```bash
cp /Users/hzuo/Documents/code/AI-Operations/codex-notification-setup/backups/hooks.json.20260719-175431.bak \
   /Users/hzuo/.codex/hooks.json
rm -f /Users/hzuo/.codex/hooks/codex-task-completed.sh
```

Then fully quit (Cmd+Q) and reopen Cursor so the extension's Codex process picks up the
restored configuration.

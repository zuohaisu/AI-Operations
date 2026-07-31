"""Per-role agent session ledger and codex session-id discovery (AIO-24).

The ledger is one JSON file inside a Run's artifact directory recording, per
role, which provider session (if any) carries context across fix attempts.
Degradation to a fresh session is always recorded, never silent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LEDGER_FILENAME = "agent-sessions.json"
_SESSION_ID_KEYS = ("thread_id", "session_id", "conversation_id")
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def parse_codex_session_id(output: Any) -> str | None:
    """Find the new session/thread id in codex ``--json`` JSONL output.

    The JSONL shape has no version guarantee, so this search is tolerant and
    a ``None`` result must always trigger the recorded degradation path.
    """
    for line in str(output or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_session_id(value)
        if found:
            return found
    return None


def _find_session_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in _SESSION_ID_KEYS:
            item = value.get(key)
            if isinstance(item, str) and item and not item.startswith("-") and _SESSION_ID_PATTERN.match(item):
                return item
        for item in value.values():
            found = _find_session_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_session_id(item)
            if found:
                return found
    return None


class SessionLedger:
    """Append-style per-role session records under one Run artifact dir."""

    def __init__(self, artifact_dir: str | Path):
        self.path = Path(artifact_dir) / LEDGER_FILENAME

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": "1.0", "sessions": {}}
        if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
            return {"schema_version": "1.0", "sessions": {}}
        return value

    def get(self, role: str) -> dict[str, Any] | None:
        entry = self.load()["sessions"].get(role)
        return entry if isinstance(entry, dict) else None

    def record(self, role: str, entry: dict[str, Any]) -> dict[str, Any]:
        ledger = self.load()
        ledger["sessions"][role] = entry
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(self.path)
        return entry

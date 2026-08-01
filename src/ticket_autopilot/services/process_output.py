"""Append-only, secret-safe backend process output for Web Runs.

The Timeline records lifecycle decisions.  This companion stream records the
human-readable output that explains what a long-running Planner, Developer,
verification command, QA, or Git command is doing while that decision is
pending.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Iterable

from ticket_autopilot.services.run_events import redact

PROCESS_OUTPUT_FILENAME = "process-output.jsonl"
_LOCK = threading.RLock()


class ProcessOutputStore:
    """Persist a small append-only stream inside one owned artifact directory."""

    def __init__(self, artifact_dir: str | Path, *, known_secrets: Iterable[str] = ()):
        self.artifact_dir = Path(artifact_dir)
        self.path = self.artifact_dir / PROCESS_OUTPUT_FILENAME
        self.known_secrets = tuple(value for value in known_secrets if isinstance(value, str) and value)

    def append(
        self,
        *,
        stage: str,
        role: str,
        stream: str,
        message: object,
        round: int = 0,
    ) -> dict[str, Any]:
        with _LOCK:
            sequence = len(self.read()) + 1
            entry = redact({
                "sequence": sequence,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "stage": stage,
                "role": role,
                "round": round,
                "stream": stream,
                "message": str(message)[:20_000],
            }, self.known_secrets)
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
            return entry

    def observer(self, *, stage: str, role: str, round: int = 0):
        """Return the callback shape consumed by the CLI driver."""
        def observe(stream: str, message: object) -> None:
            self.append(stage=stage, role=role, stream=stream, message=message, round=round)
        return observe

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(value)
        return entries

"""Append-only, secret-safe evidence events for one owned Run.

``state.json`` is a recoverable snapshot.  This module is the authoritative
history consumed by the Web Timeline; it never rewrites or derives events.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any, Iterable

EVENT_SCHEMA_VERSION = "1.0"
EVENTS_FILENAME = "events.jsonl"
MASK = "********"
_SECRET_MARKERS = ("api_key", "secret", "token", "password", "credential", "authorization")
_TOKEN_PATTERN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9_-]{8,})\b")
_LOCK = threading.RLock()


class RunEventError(RuntimeError):
    """A Run event cannot be safely written or read as evidence."""


def redact(value: Any, known_secrets: Iterable[str] = ()) -> Any:
    """Return a recursively safe copy before any artifact write or API response."""
    secrets = tuple(item for item in known_secrets if isinstance(item, str) and item)

    def clean(item: Any, key: str | None = None) -> Any:
        if key and any(marker in key.casefold() for marker in _SECRET_MARKERS):
            return MASK if item else ""
        if isinstance(item, dict):
            return {str(name): clean(child, str(name)) for name, child in item.items()}
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, tuple):
            return [clean(child) for child in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, MASK)
            return _TOKEN_PATTERN.sub(MASK, item)
        return item

    return clean(value)


def validate_event(event: Any) -> tuple[bool, list[str]]:
    """Validate the small versioned envelope needed by every Timeline reader."""
    if not isinstance(event, dict):
        return False, ["event must be an object"]
    required_strings = ("schema_version", "timestamp", "run_id", "stage", "role", "status", "event_type")
    errors = [f"event.{key} must be a non-empty string" for key in required_strings if not isinstance(event.get(key), str) or not event[key]]
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        errors.append("unsupported event schema_version")
    if not isinstance(event.get("round"), int) or event["round"] < 0:
        errors.append("event.round must be a non-negative integer")
    if not isinstance(event.get("sequence"), int) or event["sequence"] < 1:
        errors.append("event.sequence must be a positive integer")
    if not isinstance(event.get("artifact_refs"), list) or not all(isinstance(path, str) and path for path in event["artifact_refs"]):
        errors.append("event.artifact_refs must be a list of paths")
    if not isinstance(event.get("details"), dict):
        errors.append("event.details must be an object")
    return not errors, errors


class RunEventStore:
    """A single-file append-only event stream located inside a Run artifact."""

    def __init__(self, artifact_dir: str | Path, *, known_secrets: Iterable[str] = ()):
        self.artifact_dir = Path(artifact_dir)
        self.path = self.artifact_dir / EVENTS_FILENAME
        self.known_secrets = tuple(item for item in known_secrets if isinstance(item, str) and item)

    def append(
        self,
        *,
        run_id: str,
        stage: str,
        role: str,
        round: int = 0,
        status: str,
        event_type: str,
        artifact_refs: Iterable[str] = (),
        details: dict[str, Any] | None = None,
        actor_type: str = "system",
    ) -> dict[str, Any]:
        refs = list(artifact_refs)
        if not all(isinstance(path, str) and path and not Path(path).is_absolute() and ".." not in Path(path).parts for path in refs):
            raise RunEventError("event artifact references must be relative Run paths")
        with _LOCK:
            sequence = len(self.read()) + 1
            event = redact({
                "schema_version": EVENT_SCHEMA_VERSION,
                "sequence": sequence,
                "timestamp": _timestamp(),
                "run_id": run_id,
                "stage": stage,
                "role": role,
                "round": round,
                "status": status,
                "event_type": event_type,
                "actor_type": actor_type,
                "artifact_refs": refs,
                "details": details or {},
            }, self.known_secrets)
            valid, errors = validate_event(event)
            if not valid:
                raise RunEventError("invalid event: " + "; ".join(errors))
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
                output.flush()
            return event

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RunEventError("Run event artifact is unreadable") from exc
        for line_number, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunEventError(f"Run event artifact is malformed at line {line_number}") from exc
            valid, errors = validate_event(event)
            if not valid or event.get("sequence") != line_number:
                raise RunEventError(f"Run event artifact is invalid at line {line_number}: {'; '.join(errors) or 'non-monotonic sequence'}")
            events.append(event)
        return events


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

"""Deterministic Prompt reuse and bounded Planner preparation for AIO-18.

This module never starts Developer or QA.  It copies canonical task Prompts
byte-for-byte and confines generated Prompts plus provenance to one Run artifact.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any, Callable

from ticket_autopilot.services.delivery_policy import HUMAN_VISUAL_REVIEW_PENDING


_ISSUE_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)-([1-9][0-9]*)$")
_ROLES = ("dev", "acceptance")
_ACTIVE_STATES = frozenset({"ACTIVE", "PREPARING", "DEVELOPING", "VERIFYING", "QA_RUNNING"})


class PromptPreparationError(RuntimeError):
    """A Prompt cannot safely be prepared for a Run."""


class PromptResolver:
    """Resolve exact task files and create only owned preparation artifacts."""

    def __init__(self, repository: str | Path, *, artifacts_root: str | Path | None = None):
        self.repository = Path(repository).resolve()
        self.tasks = self.repository / "tasks"
        self.artifacts_root = Path(artifacts_root or self.repository / ".ticket-autopilot" / "runs").resolve()
        try:
            self.artifacts_root.relative_to(self.repository)
        except ValueError as exc:
            raise PromptPreparationError("artifact root must be inside the repository") from exc

    @staticmethod
    def task_stem(issue_key: str) -> str:
        match = _ISSUE_KEY.fullmatch(issue_key)
        if not match:
            raise PromptPreparationError("issue key must be a value such as AIO-18")
        return f"{match.group(1).upper()}-{int(match.group(2)):03d}"

    def canonical_paths(self, issue_key: str) -> dict[str, Path]:
        stem = self.task_stem(issue_key)
        return {
            "dev": self.tasks / f"{stem}-dev-prompt.md",
            "acceptance": self.tasks / f"{stem}-acceptance-prompt.md",
        }

    def availability(self, issue_key: str) -> dict[str, dict[str, str | None]]:
        return {
            role: {"available": path.is_file() and path.stat().st_size > 0,
                   "path": str(path.relative_to(self.repository)) if path.is_file() else None}
            for role, path in self.canonical_paths(issue_key).items()
        }

    def has_active_run(self) -> bool:
        if not self.artifacts_root.is_dir():
            return False
        for state_path in self.artifacts_root.glob("*/state.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(state.get("state", "")).upper() in _ACTIVE_STATES:
                return True
        for metadata_path in self.artifacts_root.glob("*/prompt-metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("status") == "PREPARING":
                return True
        return False

    def prepare(
        self,
        *,
        issue_key: str,
        ticket_spec: dict[str, Any],
        source_issue: dict[str, Any],
        planner: Callable[..., dict[str, str]] | None,
    ) -> dict[str, Any]:
        """Copy existing Prompts and call Planner exactly once for missing roles."""
        if self.has_active_run():
            raise PromptPreparationError("an owned Run is already active")
        paths = self.canonical_paths(issue_key)
        existing = {role: path for role, path in paths.items() if path.is_file() and path.stat().st_size > 0}
        missing = [role for role in _ROLES if role not in existing]
        artifact_dir = self._create_artifact_dir(issue_key)
        metadata: dict[str, Any] = {
            "schema_version": "1.0", "issue_key": issue_key, "status": "PREPARING",
            "planner_outcome": "not_needed" if not missing else "pending", "hard_break_reason": None,
            "visual_evidence": {
                "status": HUMAN_VISUAL_REVIEW_PENDING,
                "reason": "review ticket list, detail, Prompt sources, and Planner hard break in a browser",
                "draft_pr_allowed": True,
                "available_user_actions": [
                    "record_human_visual_pass",
                    "override_gate",
                ],
            },
            "prompts": {},
        }
        self._write_json(artifact_dir / "prompt-metadata.json", metadata)
        try:
            generated: dict[str, str] = {}
            if missing:
                if planner is None:
                    raise PromptPreparationError("Planner adapter is not configured")
                context = {
                    "issue_key": issue_key,
                    "plane_issue": source_issue,
                    "ticket_spec": ticket_spec,
                    "repository": ticket_spec["repository"],
                    "template_conventions": {
                        "developer": "immediate action envelope, repository invariants, diff attribution, conditional visual gate",
                        "acceptance": "immediate action envelope, independent QA boundary, diff attribution, conditional visual gate",
                    },
                }
                candidate = planner(context=context, missing_roles=tuple(missing))
                if not isinstance(candidate, dict):
                    raise PromptPreparationError("Planner returned a non-object result")
                generated = {role: candidate.get(role, "") for role in missing}
                for role, content in generated.items():
                    self._validate_generated(role, content, issue_key, ticket_spec["repository"])
                metadata["planner_outcome"] = "generated"

            for role in _ROLES:
                destination = artifact_dir / f"{role}-prompt.md"
                if role in existing:
                    destination.write_bytes(existing[role].read_bytes())
                    source = "existing_file"
                    canonical = str(existing[role].relative_to(self.repository))
                else:
                    destination.write_text(generated[role], encoding="utf-8")
                    source, canonical = "planner_generated", None
                metadata["prompts"][role] = {
                    "source": source, "canonical_path": canonical,
                    "artifact_path": str(destination.relative_to(self.repository)),
                    "status": "READY",
                }
            metadata["status"] = "READY"
        except (PromptPreparationError, TimeoutError, Exception) as exc:
            metadata["status"] = "HARD_BREAK_PLANNER"
            metadata["planner_outcome"] = "failed"
            metadata["hard_break_reason"] = str(exc) or type(exc).__name__
        self._write_json(artifact_dir / "prompt-metadata.json", metadata)
        return {**metadata, "artifact_dir": str(artifact_dir.relative_to(self.repository))}

    def _create_artifact_dir(self, issue_key: str) -> Path:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        prefix = self.task_stem(issue_key).casefold()
        while True:
            name = f"{prefix}-prompt-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}-{secrets.token_hex(3)}"
            path = self.artifacts_root / name
            try:
                path.mkdir()
                return path
            except FileExistsError:  # practically impossible, but deterministic safety costs little
                continue

    @staticmethod
    def _validate_generated(role: str, content: Any, issue_key: str, repository: str) -> None:
        if not isinstance(content, str) or not content.strip():
            raise PromptPreparationError(f"Planner returned an empty {role} Prompt")
        opening = content.lstrip()[:160].casefold()
        if "立即执行" not in opening and "execute immediately" not in opening:
            raise PromptPreparationError(f"Planner {role} Prompt has no immediate action envelope")
        lower = content.casefold()
        required = (issue_key.casefold(), repository.casefold(), "diff", "dirty", "visual")
        if any(value not in lower for value in required):
            raise PromptPreparationError(f"Planner {role} Prompt omits repository invariants or attribution/visual gate")
        if role == "dev" and "developer" not in lower:
            raise PromptPreparationError("Planner dev Prompt has no Developer role boundary")
        if role == "acceptance" and "qa" not in lower and "acceptance" not in lower:
            raise PromptPreparationError("Planner acceptance Prompt has no QA role boundary")

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

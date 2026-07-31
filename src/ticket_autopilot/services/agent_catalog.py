"""Probe-backed agent provider catalog and safe CLI call construction.

This module owns three concerns for the local web console (AIO-22):

* a fixed registry of supported agent providers (codex / claude / qodercli)
  holding only *call-protocol* metadata, never model names;
* a capability probe that discovers each provider's availability, version,
  and model/reasoning options from the local machine at runtime;
* a builder that turns a validated role profile into an agent dict for
  ``ticket_autopilot.engine.drivers.cli_call``.

Workflow execution, guardrails, and retry decisions stay in the engine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any, Callable, Mapping

from ticket_autopilot.engine.guardrails import DEFAULT_TOOL_WHITELIST, DEVELOPER_TOOL_WHITELIST

ROLES = ("planner", "developer", "qa")
PROFILE_KEYS = ("provider", "model", "reasoning", "permission_mode")
PROBE_TIMEOUT_SECONDS = 10
CATALOG_TTL_SECONDS = 300.0
# Values are spliced into argv (and, for codex, a TOML literal); keep them to a
# conservative token alphabet so a profile can never smuggle an extra flag.
_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_CLAUDE_EFFORT_HELP = re.compile(r"--effort\s+<[^>]*>[^(]*\(([^)]+)\)")
# Each CLI publishes its permission/sandbox vocabulary in --help; probing it
# keeps the console dropdown in sync with the installed version instead of a
# hardcoded list that drifts (see the qodercli "read-only" hard break).
_PERMISSION_MODE_HELP = re.compile(r"--permission-mode[\s\S]{0,240}?\(choices:\s*([^)]*)\)")
_CODEX_SANDBOX_HELP = re.compile(r"--sandbox[\s\S]{0,300}?\[possible values:\s*([^\]]*)\]")
# Only modes that never auto-approve mutations may back a read-only role
# (planner/QA); anything else is rejected at validation time.
_READ_ONLY_SAFE_MODES = {"default", "plan", "manual", "readonly"}

PROVIDERS: dict[str, dict[str, str]] = {
    "codex": {"label": "Codex CLI", "command": "codex"},
    "claude": {"label": "Claude Code", "command": "claude"},
    "qodercli": {"label": "Qoder CLI", "command": "qodercli"},
}


class CatalogError(ValueError):
    """A role profile falls outside the probed local capability catalog."""


def empty_profile() -> dict[str, str]:
    return {key: "" for key in PROFILE_KEYS}


def normalize_profile(value: Any) -> dict[str, str]:
    """Coerce a stored agents entry (legacy string or dict) into profile shape.

    Legacy configs stored a bare CLI command name.  A recognised provider name
    is kept; anything else is dropped so an arbitrary saved string can never be
    interpreted as a command again.
    """
    if isinstance(value, Mapping):
        return {key: item if isinstance(item := value.get(key, ""), str) else "" for key in PROFILE_KEYS}
    provider = value.strip() if isinstance(value, str) else ""
    return {**empty_profile(), "provider": provider if provider in PROVIDERS else ""}


class AgentCatalog:
    """Local capability catalog with a TTL cache; probes never raise upward."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        codex_config_path: str | Path | None = None,
        ttl: float = CATALOG_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.runner = runner
        self.which = which
        self.codex_config_path = Path(codex_config_path) if codex_config_path else Path.home() / ".codex" / "config.toml"
        self.ttl = ttl
        self.clock = clock
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}

    # -- probing ------------------------------------------------------------

    def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        return {"providers": {name: self.provider(name, refresh=refresh) for name in PROVIDERS}}

    def provider(self, name: str, *, refresh: bool = False) -> dict[str, Any]:
        if name not in PROVIDERS:
            raise CatalogError(f"unknown agent provider: {name!r}")
        cached = self._cache.get(name)
        if not refresh and cached is not None and self.clock() - cached[1] < self.ttl:
            return cached[0]
        entry = self._probe(name)
        self._cache[name] = (entry, self.clock())
        return entry

    def _probe(self, name: str) -> dict[str, Any]:
        spec = PROVIDERS[name]
        entry: dict[str, Any] = {
            "label": spec["label"], "command": spec["command"], "available": False,
            "reason": "", "version": "", "models": [], "reasoning": [], "permission_modes": [],
        }
        try:
            if not self.which(spec["command"]):
                entry["reason"] = f"{spec['command']} is not on PATH"
                return entry
            version = self._run([spec["command"], "--version"])
            if version is None:
                entry["reason"] = f"{spec['command']} --version failed"
                return entry
            models, reasoning, permission_modes = getattr(self, f"_options_{name}")()
            entry.update({
                "available": True,
                "version": version.strip().splitlines()[0] if version.strip() else "",
                "models": models, "reasoning": reasoning, "permission_modes": permission_modes,
            })
        except Exception as exc:  # a broken probe degrades, it never breaks the API
            entry.update({"available": False, "reason": f"probe failed: {exc}"[:200]})
        return entry

    def _run(self, cmd: list[str]) -> str | None:
        try:
            proc = self.runner(cmd, capture_output=True, text=True, check=False,
                               timeout=PROBE_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None

    def _options_codex(self) -> tuple[list[str], list[str], list[str]]:
        # codex has no non-interactive model listing; the user's own config.toml
        # is the only trustworthy local source of a known-good model/effort.
        try:
            with open(self.codex_config_path, "rb") as handle:
                config = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            config = {}
        # codex's permission analog is the -s sandbox policy from --help.
        help_text = self._run([PROVIDERS["codex"]["command"], "--help"]) or ""
        match = _CODEX_SANDBOX_HELP.search(help_text)
        modes = match.group(1).split(",") if match else []
        return (_clean_values([config.get("model")]),
                _clean_values([config.get("model_reasoning_effort")]),
                _clean_values(modes))

    def _options_claude(self) -> tuple[list[str], list[str], list[str]]:
        help_text = self._run([PROVIDERS["claude"]["command"], "--help"]) or ""
        match = _CLAUDE_EFFORT_HELP.search(help_text)
        levels = match.group(1).split(",") if match else []
        return [], _clean_values(levels), _permission_modes_from_help(help_text)

    def _options_qodercli(self) -> tuple[list[str], list[str], list[str]]:
        listing = self._run([PROVIDERS["qodercli"]["command"], "--list-models"]) or ""
        models = [line for line in (raw.strip() for raw in listing.splitlines())
                  if line and line.upper() != "MODEL"]
        help_text = self._run([PROVIDERS["qodercli"]["command"], "--help"]) or ""
        return _clean_values(models), [], _permission_modes_from_help(help_text)

    # -- validation ---------------------------------------------------------

    def validate_profile(self, role: str, profile: Any) -> dict[str, str]:
        """Return a normalized profile or raise; the catalog is the value gate."""
        if role not in ROLES:
            raise CatalogError(f"unknown agent role: {role!r}")
        if not isinstance(profile, Mapping):
            raise CatalogError(f"agents.{role} must be an object")
        unknown = sorted(set(profile) - set(PROFILE_KEYS))
        if unknown:
            raise CatalogError(f"agents.{role} has unsupported fields: {unknown}")
        checked = {}
        for key in PROFILE_KEYS:
            value = profile.get(key, "")
            if not isinstance(value, str):
                raise CatalogError(f"agents.{role}.{key} must be a string")
            if value and not _VALUE_PATTERN.match(value):
                raise CatalogError(f"agents.{role}.{key} contains unsupported characters")
            checked[key] = value
        if not checked["provider"]:
            if checked["model"] or checked["reasoning"]:
                raise CatalogError(f"agents.{role} model/reasoning require a provider")
            return checked
        if checked["provider"] not in PROVIDERS:
            raise CatalogError(f"agents.{role}.provider must be one of {sorted(PROVIDERS)}")
        entry = self.provider(checked["provider"])
        if not entry["available"]:
            raise CatalogError(f"agents.{role}.provider {checked['provider']} is unavailable: {entry['reason']}")
        if checked["model"] and checked["model"] not in entry["models"]:
            raise CatalogError(f"agents.{role}.model {checked['model']!r} is not in the probed catalog")
        if checked["reasoning"] and checked["reasoning"] not in entry["reasoning"]:
            raise CatalogError(f"agents.{role}.reasoning {checked['reasoning']!r} is not in the probed catalog")
        if checked["permission_mode"]:
            if checked["permission_mode"] not in entry["permission_modes"]:
                raise CatalogError(f"agents.{role}.permission_mode {checked['permission_mode']!r} is not in the probed catalog")
            if role != "developer" and not _is_read_only_safe(checked["permission_mode"]):
                raise CatalogError(
                    f"agents.{role} is a read-only role and cannot use permission mode {checked['permission_mode']!r}")
        return checked

    # -- call construction ----------------------------------------------------

    def build_agent(
        self,
        profile: Any,
        *,
        role: str,
        cwd: str,
        allowed_roots: list[str],
        system: str = "",
        expect: str | None = None,
        session: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a ``drivers.cli_call`` agent dict from a validated profile.

        Guardrail enforcement stays in the engine: this only chooses the
        provider-correct flag shapes that the drivers already support.

        ``session`` explicitly controls session lifecycle per AIO-24:
        ``{"mode": "new"|"resume"|"ephemeral", "session_id": ...}``.  Resume
        always requires an explicit valid id, so a wildcard resume such as
        codex ``--last`` is structurally impossible.  ``None`` keeps the
        AIO-22 defaults (read-only roles are ephemeral).
        """
        checked = self.validate_profile(role, profile)
        provider = checked["provider"]
        if not provider:
            raise CatalogError(f"agents.{role} has no provider configured")
        mode, session_id = self._check_session(provider, session)
        writable = role == "developer"
        tools = list(DEVELOPER_TOOL_WHITELIST if writable else DEFAULT_TOOL_WHITELIST)
        base: dict[str, Any] = {
            "driver": "cli", "role": role, "cwd": cwd,
            "allowed_roots": list(allowed_roots),
            "permission_mode": "write" if writable else "read-only",
            "tools": tools, "read_only": not writable, "tool_whitelist": tools,
            "provider": provider, "model": checked["model"], "reasoning": checked["reasoning"],
        }
        if system:
            base["system"] = system
        if expect:
            base["expect"] = expect

        if provider == "codex":
            argv = ["codex", "exec"]
            if mode == "resume":
                argv += ["resume", session_id]
            sandbox = checked["permission_mode"] or ("workspace-write" if writable else "read-only")
            argv += ["-s", sandbox,
                     "-C", "{cwd}", "--skip-git-repo-check", "--color", "never"]
            if mode == "ephemeral" or (mode is None and not writable):
                argv.append("--ephemeral")
            elif mode == "new":
                # --json emits JSONL carrying the new session/thread id.
                argv.append("--json")
            if checked["model"]:
                argv += ["-m", checked["model"]]
            if checked["reasoning"]:
                argv += ["-c", f'model_reasoning_effort="{checked["reasoning"]}"']
            argv.append("{prompt}")
            return {**base, "argv": argv}

        agent = {**base, "command": PROVIDERS[provider]["command"]}
        if checked["permission_mode"]:
            # An explicit probed choice overrides the driver's default mapping.
            agent["cli_permission_mode"] = checked["permission_mode"]
        extra: list[str] = []
        if checked["model"]:
            extra += ["--model" if provider == "claude" else "-m", checked["model"]]
        if checked["reasoning"]:
            extra += ["--effort" if provider == "claude" else "--reasoning-effort", checked["reasoning"]]
        if provider == "qodercli":
            agent.update({"tools_flag": "--tools", "tools_as_args": True})
            if not writable:
                # --allowed-tools auto-approves only read tools in -p mode.
                extra += ["--allowed-tools", ",".join(tools)]
        if mode == "new":
            extra += ["--session-id", session_id]
        elif mode == "resume":
            extra += ["-r", session_id]
        elif mode == "ephemeral" or (mode is None and not writable):
            extra += ["--no-session-persistence"]
        if extra:
            agent["extra_args"] = extra
        return agent

    @staticmethod
    def _check_session(provider: str, session: Mapping[str, Any] | None) -> tuple[str | None, str]:
        if session is None:
            return None, ""
        mode = session.get("mode")
        if mode not in ("new", "resume", "ephemeral"):
            raise CatalogError(f"session mode must be new/resume/ephemeral, not {mode!r}")
        session_id = session.get("session_id") or ""
        if session_id and (not isinstance(session_id, str) or session_id.startswith("-")
                           or not _VALUE_PATTERN.match(session_id)):
            raise CatalogError("session id contains unsupported characters")
        if mode == "resume" and not session_id:
            raise CatalogError("session resume requires an explicit session id")
        if mode == "new" and provider != "codex" and not session_id:
            raise CatalogError(f"a new {provider} session requires a pre-generated session id")
        return mode, session_id


def _clean_values(values: Any) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        if isinstance(value, str) and _VALUE_PATTERN.match(value.strip()):
            cleaned.append(value.strip())
    return cleaned


def _permission_modes_from_help(help_text: str) -> list[str]:
    match = _PERMISSION_MODE_HELP.search(help_text)
    if not match:
        return []
    # claude quotes its choices ("acceptEdits"); qodercli lists them bare.
    return _clean_values([value.strip().strip('"') for value in match.group(1).split(",")])


def _is_read_only_safe(mode: str) -> bool:
    return mode.casefold().replace("_", "").replace("-", "") in _READ_ONLY_SAFE_MODES

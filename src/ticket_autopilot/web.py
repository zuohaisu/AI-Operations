"""Local-only settings server and lifecycle manager for Ticket Autopilot.

This module intentionally does not invoke the ticket controller, Plane, or an
Agent.  It supplies only the persistent local entrypoint that those later
features can reuse.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlparse

from ticket_autopilot.connectors import plane
from ticket_autopilot.services.agent_catalog import AgentCatalog, CatalogError, PROFILE_KEYS, empty_profile, normalize_profile
from ticket_autopilot.services.prompt_resolver import PromptPreparationError, PromptResolver
from ticket_autopilot.services.process_output import ProcessOutputStore
from ticket_autopilot.services.ticket_contract import preflight_plane_issue, readiness_errors
from ticket_autopilot.services.run_events import redact
from ticket_autopilot.services.run_manager import RunManager
from ticket_autopilot.services.web_agent_loop import WebAgentLoop, WebAgentLoopError
from urllib.request import Request, urlopen
import webbrowser

HOST = "127.0.0.1"
PORT = 8765
APP_DIRECTORY = ".ticket-autopilot"
CONFIG_FILENAME = "config.json"
SERVICE_FILENAME = "service.json"
LOG_DIRECTORY = "logs"
LOG_FILENAME = "server.log"
MASK = "********"

_DEFAULT_CONFIG: dict[str, Any] = {
    "plane": {"workspace": "", "project": "", "api_key": ""},
    "repository": "",
    "agents": {"planner": empty_profile(), "developer": empty_profile(), "qa": empty_profile()},
}
_SECRET_MARKERS = ("api_key", "secret", "token", "password", "credential")


class LocalServiceError(RuntimeError):
    """A local service operation could not be completed safely."""


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _replace_repository_path(value: Any, source: str, worktree: str) -> Any:
    """Replace source-checkout paths in every Agent-visible string."""
    if isinstance(value, dict):
        return {key: _replace_repository_path(item, source, worktree) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_repository_path(item, source, worktree) for item in value]
    if isinstance(value, str):
        return value.replace(source, worktree)
    return value


def _bind_agent_inputs(
    ticket_spec: dict[str, Any], prompt: str, *, repository: str | Path, worktree: str | Path,
) -> tuple[dict[str, Any], str]:
    """Return an Agent contract that names only the disposable Run worktree."""
    source = str(Path(repository).resolve())
    target = str(Path(worktree).resolve())
    bound_spec = _replace_repository_path(_copy_json(ticket_spec), source, target)
    bound_spec["repository"] = target
    bound_prompt = prompt.replace(source, target)
    boundary = (
        "RUNTIME WORKTREE BOUNDARY: The only repository you may inspect or modify is "
        f"{target}. Treat every relative path as relative to this directory. Do not access "
        "any source checkout outside this worktree.\n\n"
    )
    return bound_spec, boundary + bound_prompt


def _verification_commands(ticket_spec: dict[str, Any]) -> list[str]:
    """Return each executable ticket check once, preserving contract order."""
    commands = [
        item["command"]
        for item in ticket_spec.get("verification", [])
        if item.get("type") in {"automated", "query"} and item.get("command")
    ]
    commands.extend(ticket_spec.get("required_checks", []))
    return list(dict.fromkeys(commands))


def _verification_environment(repository: Path) -> dict[str, str]:
    """Make the service/project Python environment available to ticket checks."""
    environment = os.environ.copy()
    path_entries: list[str] = []
    for candidate in (repository / ".venv" / "bin", Path(sys.executable).parent):
        candidate_text = str(candidate)
        if candidate.is_dir() and candidate_text not in path_entries:
            path_entries.append(candidate_text)
    current_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join([*path_entries, current_path])
    return environment


def app_home(home: str | Path | None = None) -> Path:
    """Return the private per-user state directory (overridable for tests)."""
    return Path(home) if home is not None else Path.home() / APP_DIRECTORY


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace a private JSON file, never exposing a partial file."""
    _private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _private_file(path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def redact_secrets(value: Any) -> Any:
    """Recursively mask values whose field names could carry credentials."""
    if isinstance(value, dict):
        return {
            key: (MASK if any(marker in key.casefold() for marker in _SECRET_MARKERS) and item else
                  ("" if any(marker in key.casefold() for marker in _SECRET_MARKERS) else redact_secrets(item)))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


class LocalConfig:
    """Private JSON-backed local settings with a deliberately small schema."""

    def __init__(self, home: str | Path | None = None,
                 agent_profile_validator: Callable[[str, dict[str, str]], dict[str, str]] | None = None):
        self.home = app_home(home)
        self.path = self.home / CONFIG_FILENAME
        self.agent_profile_validator = agent_profile_validator
        _private_directory(self.home)

    def load(self, *, redacted: bool = True) -> dict[str, Any]:
        stored = _read_json(self.path) or {}
        if isinstance(stored.get("agents"), dict):
            # Legacy configs stored a bare command string per role; normalise
            # to the structured profile shape before the type-driven merge.
            stored = {**stored, "agents": {
                role: normalize_profile(value) for role, value in stored["agents"].items()
            }}
        config = _copy_json(_DEFAULT_CONFIG)
        self._merge(config, stored)
        _private_file(self.path) if self.path.exists() else None
        return redact_secrets(config) if redacted else config

    def save(self, incoming: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise LocalServiceError("settings must be a JSON object")
        current = self.load(redacted=False)
        updated = _copy_json(current)
        self._merge_allowed(updated, incoming)
        if self.agent_profile_validator is not None and isinstance(incoming.get("agents"), dict):
            for role in ("planner", "developer", "qa"):
                if role in incoming["agents"]:
                    updated["agents"][role] = self.agent_profile_validator(role, updated["agents"][role])
        atomic_json_write(self.path, updated)
        return redact_secrets(updated)

    @staticmethod
    def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                LocalConfig._merge(target[key], value)
            elif key in target and isinstance(target[key], str) and isinstance(value, str):
                target[key] = value

    @staticmethod
    def _merge_allowed(target: dict[str, Any], incoming: dict[str, Any]) -> None:
        for key in ("repository",):
            if key in incoming:
                if not isinstance(incoming[key], str):
                    raise LocalServiceError(f"{key} must be a string")
                target[key] = incoming[key]
        if "plane" in incoming:
            supplied = incoming["plane"]
            if not isinstance(supplied, dict):
                raise LocalServiceError("plane must be an object")
            for key in ("workspace", "project", "api_key"):
                if key in supplied:
                    if not isinstance(supplied[key], str):
                        raise LocalServiceError(f"plane.{key} must be a string")
                    # A settings page sends the displayed mask back unchanged;
                    # that must not overwrite a real saved credential.
                    if key == "api_key" and supplied[key] == MASK:
                        continue
                    target["plane"][key] = supplied[key]
        if "agents" in incoming:
            supplied = incoming["agents"]
            if not isinstance(supplied, dict):
                raise LocalServiceError("agents must be an object")
            for role in ("planner", "developer", "qa"):
                if role not in supplied:
                    continue
                value = supplied[role]
                if not isinstance(value, (str, dict)):
                    raise LocalServiceError(f"agents.{role} must be an object")
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key not in PROFILE_KEYS or not isinstance(item, str):
                            raise LocalServiceError(f"agents.{role}.{key} is not a supported string field")
                target["agents"][role] = normalize_profile(value)


class ServiceManager:
    """Start and stop only a server whose process and health identity match."""

    def __init__(
        self,
        *,
        home: str | Path | None = None,
        port: int = PORT,
        project_root: str | Path | None = None,
        browser_opener: Callable[[str], Any] = webbrowser.open,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ):
        self.home = app_home(home)
        self.port = port
        self.project_root = Path(project_root or os.environ.get("TICKET_AUTOPILOT_PROJECT_ROOT") or Path.cwd()).resolve()
        self.browser_opener = browser_opener
        self.popen = popen
        self.service_path = self.home / SERVICE_FILENAME
        self.log_path = self.home / LOG_DIRECTORY / LOG_FILENAME
        self._children: dict[int, subprocess.Popen[bytes]] = {}
        _private_directory(self.home)
        _private_directory(self.log_path.parent)

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def start(self, *, open_browser: bool = True) -> int:
        record = self._record()
        if self._is_owned_running(record):
            if open_browser:
                self._open_browser()
            print(f"Ticket Autopilot is already running at {self.url}")
            return 0
        if record is not None:
            # A stale or unverifiable ledger is never permission to signal its PID.
            self._remove_record()
        if not self._port_is_available():
            print(f"Cannot start Ticket Autopilot: {HOST}:{self.port} is in use by another process.", file=sys.stderr)
            return 1

        service_id = secrets.token_urlsafe(32)
        self._prepare_log()
        command = [
            sys.executable, "-m", "ticket_autopilot.web", "server",
            "--port", str(self.port), f"--service-id={service_id}",
            "--home", str(self.home),
        ]
        try:
            with self.log_path.open("ab", buffering=0) as log:
                process = self.popen(
                    command, cwd=self.project_root, stdout=log, stderr=log,
                    start_new_session=True, close_fds=True,
                )
        except OSError as exc:
            print(f"Cannot start Ticket Autopilot: {exc.strerror or 'could not create server process'}.", file=sys.stderr)
            return 1

        self._children[process.pid] = process
        record = {
            "schema_version": 1,
            "pid": process.pid,
            "process_group": process.pid,
            "host": HOST,
            "port": self.port,
            "service_id": service_id,
            "project_root": str(self.project_root),
        }
        try:
            atomic_json_write(self.service_path, record)
        except OSError:
            # The just-created process is identifiable by its one-time service id.
            self._terminate_if_owned(record)
            print("Cannot start Ticket Autopilot: could not securely save service identity.", file=sys.stderr)
            return 1
        if not self._wait_for_health(record):
            self._terminate_if_owned(record)
            self._remove_record()
            print("Cannot start Ticket Autopilot: health check timed out; see ~/.ticket-autopilot/logs/server.log.", file=sys.stderr)
            return 1
        if open_browser:
            self._open_browser()
        print(f"Ticket Autopilot is running at {self.url}")
        return 0

    def status(self) -> int:
        if self._is_owned_running(self._record()):
            print(f"Ticket Autopilot is running at {self.url}")
            return 0
        print("Ticket Autopilot is stopped")
        return 1

    def stop(self) -> int:
        record = self._record()
        if record is None:
            print("Ticket Autopilot is already stopped")
            return 0
        if not self._is_owned_running(record):
            self._remove_record()
            print("Ticket Autopilot is stopped (stale service record removed)")
            return 0
        if not self._terminate_if_owned(record):
            print("Cannot stop Ticket Autopilot: service ownership could not be verified.", file=sys.stderr)
            return 1
        self._remove_record()
        print("Ticket Autopilot stopped")
        return 0

    def restart(self, *, open_browser: bool = True) -> int:
        if self.stop() != 0:
            return 1
        return self.start(open_browser=open_browser)

    def _record(self) -> dict[str, Any] | None:
        record = _read_json(self.service_path)
        if record is not None:
            _private_file(self.service_path)
        return record

    def _remove_record(self) -> None:
        try:
            self.service_path.unlink()
        except FileNotFoundError:
            pass

    def _prepare_log(self) -> None:
        self.log_path.touch(exist_ok=True)
        _private_file(self.log_path)

    def _port_is_available(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                candidate.bind((HOST, self.port))
            except OSError:
                # Never treat an unavailable or occupied port as ours.
                return False
        return True

    def _is_owned_running(self, record: dict[str, Any] | None) -> bool:
        return self._matches_process(record) and self._healthy(record)  # type: ignore[arg-type]

    def _matches_process(self, record: dict[str, Any] | None) -> bool:
        """Verify the record against PID, process group, and one-time command ID."""
        if not self._valid_record(record):
            return False
        assert record is not None
        pid, group = record["pid"], record["process_group"]
        try:
            os.kill(pid, 0)
            if os.getpgid(pid) != group or group != pid:
                return False
        except OSError:
            return False
        command = _process_command(pid)
        return bool(command and "ticket_autopilot.web" in command and record["service_id"] in command)

    def _valid_record(self, record: dict[str, Any] | None) -> bool:
        if not isinstance(record, dict):
            return False
        return (
            record.get("schema_version") == 1
            and record.get("host") == HOST
            and record.get("port") == self.port
            and isinstance(record.get("pid"), int) and record["pid"] > 1
            and isinstance(record.get("process_group"), int)
            and isinstance(record.get("service_id"), str) and len(record["service_id"]) >= 20
        )

    def _healthy(self, record: dict[str, Any]) -> bool:
        try:
            request = Request(f"http://{HOST}:{self.port}/api/health", headers={"Accept": "application/json"})
            with urlopen(request, timeout=0.4) as response:
                data = json.loads(response.read().decode("utf-8"))
            return response.status == HTTPStatus.OK and data == {"status": "ok", "service_id": record["service_id"]}
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            return False

    def _wait_for_health(self, record: dict[str, Any], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._healthy(record):
                return True
            try:
                os.kill(record["pid"], 0)
            except OSError:
                return False
            time.sleep(0.05)
        return False

    def _terminate_if_owned(self, record: dict[str, Any]) -> bool:
        # Health may be unavailable during startup failure, but the PID/session
        # and unguessable per-launch ID still prove this exact child is ours.
        if not self._matches_process(record):
            return False
        try:
            os.killpg(record["process_group"], signal.SIGTERM)
        except OSError:
            return False
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            child = self._children.get(record["pid"])
            if child is not None and child.poll() is not None:
                self._children.pop(record["pid"], None)
                return True
            try:
                os.kill(record["pid"], 0)
            except OSError:
                self._children.pop(record["pid"], None)
                return True
            time.sleep(0.05)
        return False

    def _open_browser(self) -> None:
        try:
            self.browser_opener(self.url)
        except Exception:
            # A running local service is still usable when a desktop browser is unavailable.
            pass


def _process_command(pid: int) -> str | None:
    """Read a process command without shelling out or accepting arbitrary PID data."""
    proc_command = Path("/proc") / str(pid) / "cmdline"
    try:
        return proc_command.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
    except OSError:
        pass
    try:
        completed = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
        return completed.stdout.strip() if completed.returncode == 0 else None
    except OSError:
        return None


class TicketBoard:
    """Thin Web boundary over the existing Plane connector and ticket contract."""

    def __init__(self, settings: LocalConfig, *, repository: str | Path | None = None, planner: Callable[..., dict[str, str]] | None = None,
                 web_loop_factory: Callable[..., WebAgentLoop] | None = None, catalog: AgentCatalog | None = None):
        self.settings = settings
        self.repository = Path(repository or Path.cwd()).resolve()
        self.catalog = catalog or AgentCatalog()
        if planner is None:
            from ticket_autopilot.services.planner_adapter import build_planner
            planner = build_planner(settings, self.repository, self.catalog)
        self.planner = planner
        self.web_loop_factory = web_loop_factory or self._default_web_loop
        self._web_loops: dict[str, WebAgentLoop] = {}
        self.operations_root = self.repository / ".ticket-autopilot" / "operations"
        self._operation_lock = threading.RLock()
        self._operation_threads: dict[str, threading.Thread] = {}

    def list(self) -> dict[str, Any]:
        items = plane.list_work_items(**self._plane_options())
        return {"tickets": [self._summary(item) for item in items if plane.is_unfinished_work_item(item)]}

    def detail(self, issue_id: str) -> dict[str, Any]:
        item = plane.fetch_issue(issue_id, **self._plane_options())
        return self._detail(item)

    def prepare(self, issue_id: str) -> dict[str, Any]:
        item = plane.fetch_issue(issue_id, **self._plane_options())
        detail = self._detail(item)
        if not detail["eligible"]:
            return {"status": "BLOCKED_REQUIREMENTS", "reason": detail["reason"], "developer_calls": 0, "qa_calls": 0}
        resolver = PromptResolver(self.repository)
        try:
            prepared = resolver.prepare(
                issue_key=item["identifier"], ticket_spec=detail["ticket_spec"],
                source_issue=item, planner=self.planner,
            )
        except PromptPreparationError as exc:
            return {"status": "BLOCKED_REQUIREMENTS", "reason": str(exc), "developer_calls": 0, "qa_calls": 0}
        return {**prepared, "developer_calls": 0, "qa_calls": 0}

    def run(
        self, issue_id: str, *, process_observer: Callable[[str, object], None] | None = None,
    ) -> dict[str, Any]:
        """Prepare missing Prompts, then start one Web Run from a single action."""
        if process_observer is not None:
            process_observer("process", "fetching and validating the Plane ticket")
        item = plane.fetch_issue(issue_id, **self._plane_options())
        detail = self._detail(item)
        if not detail["eligible"]:
            return {"status": "BLOCKED_REQUIREMENTS", "reason": detail["reason"], "run_id": None,
                    "developer_calls": 0, "qa_calls": 0}
        resolver = PromptResolver(self.repository)
        paths = resolver.canonical_paths(detail["identifier"])
        prepared: dict[str, Any] | None = None
        try:
            developer_prompt = paths["dev"].read_text(encoding="utf-8")
            qa_prompt = paths["acceptance"].read_text(encoding="utf-8")
            if process_observer is not None:
                process_observer("process", "reusing existing Developer and QA prompt files")
        except OSError:
            if process_observer is not None:
                process_observer("process", "one or more prompts are missing; starting Planner")
            try:
                prepared = resolver.prepare(
                    issue_key=item["identifier"], ticket_spec=detail["ticket_spec"],
                    source_issue=item, planner=self.planner, process_observer=process_observer,
                )
            except PromptPreparationError as exc:
                return {"status": "BLOCKED_REQUIREMENTS", "reason": str(exc), "run_id": None,
                        "developer_calls": 0, "qa_calls": 0}
            if prepared.get("status") != "READY":
                return {
                    "status": str(prepared.get("status") or "HARD_BREAK_PLANNER"),
                    "reason": str(prepared.get("hard_break_reason") or "Planner did not prepare runnable Prompts"),
                    "artifact_dir": prepared.get("artifact_dir"), "run_id": None,
                    "developer_calls": 0, "qa_calls": 0,
                }
            artifact_dir = self.repository / str(prepared["artifact_dir"])
            try:
                developer_prompt = (artifact_dir / "dev-prompt.md").read_text(encoding="utf-8")
                qa_prompt = (artifact_dir / "acceptance-prompt.md").read_text(encoding="utf-8")
            except OSError as exc:
                return {"status": "HARD_BREAK_PLANNER", "reason": f"prepared Prompt artifact is unavailable: {exc}",
                        "artifact_dir": prepared.get("artifact_dir"), "run_id": None,
                        "developer_calls": 0, "qa_calls": 0}

        if prepared is None:
            prompt_sources = {
                role: {"source": "existing_file", "canonical_path": str(path.relative_to(self.repository))}
                for role, path in paths.items()
            }
        else:
            prompt_sources = prepared["prompts"]
        try:
            loop = self.web_loop_factory(settings=self.settings, repository=self.repository)
            result = loop.start(
                detail["ticket_spec"], developer_prompt=developer_prompt, qa_prompt=qa_prompt,
                prompt_sources=prompt_sources,
            )
            if result.get("run_id"):
                self._web_loops[str(result["run_id"])] = loop
            if prepared is not None:
                result["preparation"] = {
                    "status": prepared["status"], "artifact_dir": prepared["artifact_dir"],
                    "planner_outcome": prepared["planner_outcome"],
                    "planner_attempts": prepared.get("planner_attempts", 0),
                }
            return result
        except WebAgentLoopError as exc:
            return {"status": "BLOCKED_REQUIREMENTS", "reason": str(exc), "run_id": None,
                    "developer_calls": 0, "qa_calls": 0}

    def start_run(self, issue_id: str) -> dict[str, Any]:
        """Return immediately with an observable operation while preparation runs."""
        with self._operation_lock:
            for state_path in self.operations_root.glob("*/state.json") if self.operations_root.is_dir() else ():
                state = _read_json(state_path) or {}
                if state.get("status") in {"PREPARING", "STARTING"}:
                    return {
                        "status": "BLOCKED",
                        "reason": "another Run preparation is already active",
                        "operation_id": state.get("operation_id"),
                        "run_id": state.get("run_id"),
                    }
            operation_id = f"operation-{int(time.time() * 1_000_000)}-{secrets.token_hex(3)}"
            artifact_dir = self.operations_root / operation_id
            artifact_dir.mkdir(parents=True, exist_ok=False)
            state = {
                "schema_version": "1.0",
                "operation_id": operation_id,
                "issue_id": issue_id,
                "status": "PREPARING",
                "stage": "planner",
                "run_id": None,
                "reason": None,
                "artifact_dir": str(artifact_dir),
            }
            atomic_json_write(artifact_dir / "state.json", state)
            output = ProcessOutputStore(artifact_dir, known_secrets=(
                self.settings.load(redacted=False)["plane"].get("api_key", ""),
            ))
            output.append(stage="planner", role="controller", stream="process",
                          message="Run request accepted; preparing ticket and prompts")
            thread = threading.Thread(
                target=self._execute_operation,
                args=(operation_id,),
                daemon=True,
                name=f"ticket-autopilot-{operation_id}",
            )
            self._operation_threads[operation_id] = thread
            thread.start()
        return {"status": "PREPARING", "operation_id": operation_id, "run_id": None}

    def operation(self, operation_id: str) -> dict[str, Any]:
        if not operation_id.startswith("operation-") or "/" in operation_id or ".." in operation_id:
            raise ValueError("invalid operation id")
        artifact_dir = self.operations_root / operation_id
        state = _read_json(artifact_dir / "state.json")
        if state is None:
            raise ValueError("unknown operation")
        secret_values = (self.settings.load(redacted=False)["plane"].get("api_key", ""),)
        return {
            **redact(state, secret_values),
            "process_output": ProcessOutputStore(
                artifact_dir, known_secrets=secret_values,
            ).read(),
        }

    def _execute_operation(self, operation_id: str) -> None:
        artifact_dir = self.operations_root / operation_id
        state = _read_json(artifact_dir / "state.json") or {}
        secret_values = (self.settings.load(redacted=False)["plane"].get("api_key", ""),)
        output = ProcessOutputStore(artifact_dir, known_secrets=secret_values)
        try:
            result = self.run(
                str(state["issue_id"]),
                process_observer=output.observer(stage="planner", role="planner"),
            )
            run_id = result.get("run_id")
            state.update({
                "status": "RUNNING" if run_id else str(result.get("status") or "BLOCKED"),
                "stage": "run" if run_id else "planner",
                "run_id": run_id,
                "reason": result.get("reason"),
                "result": result,
            })
            if run_id:
                run_record = RunManager(self.repository, known_secrets=secret_values).load_run(str(run_id))
                run_output = ProcessOutputStore(run_record.artifact_dir, known_secrets=secret_values)
                for entry in output.read():
                    run_output.append(stage=entry.get("stage", "planner"), role=entry.get("role", "planner"),
                                      stream=entry.get("stream", "process"), message=entry.get("message", ""),
                                      round=int(entry.get("round") or 0))
                run_output.append(stage="run", role="controller", stream="process",
                                  message=f"created isolated Run {run_id}")
            else:
                output.append(stage="planner", role="controller", stream="process",
                              message=f"preparation stopped: {state['status']} {state.get('reason') or ''}")
        except Exception as exc:
            state.update({"status": "HARD_BREAK", "stage": "planner", "run_id": None,
                          "reason": str(exc) or type(exc).__name__})
            output.append(stage="planner", role="controller", stream="stderr", message=state["reason"])
        finally:
            atomic_json_write(artifact_dir / "state.json", state)

    def _default_web_loop(self, *, settings: LocalConfig, repository: Path) -> WebAgentLoop:
        """Build the one product adapter; individual external calls remain isolated."""
        import uuid

        from ticket_autopilot.connectors import qa
        from ticket_autopilot.engine import drivers
        from ticket_autopilot.engine.guardrails import (
            DEVELOPER_TOOL_WHITELIST, GuardrailPolicy, RunExecutionContext,
        )
        from ticket_autopilot.services.agent_sessions import (
            LEDGER_FILENAME, SessionLedger, parse_codex_session_id,
        )

        catalog = self.catalog
        profiles = settings.load(redacted=False)["agents"]
        developer_profile, qa_profile = profiles.get("developer"), profiles.get("qa")
        if not (developer_profile or {}).get("provider") or not (qa_profile or {}).get("provider"):
            raise WebAgentLoopError("BLOCKED_REQUIREMENTS: configure Developer and QA Agent providers")

        secret_values = (settings.load(redacted=False)["plane"].get("api_key", ""),)
        run_manager = RunManager(repository, known_secrets=secret_values)

        def session_event(run: dict[str, Any], *, stage: str, role: str, status: str,
                          event_type: str, details: dict[str, Any], round: int = 0) -> None:
            actor = "qa_agent" if role == "qa" else "developer_agent"
            run_manager.append_event(run["run_id"], stage=stage, role=role, status=status,
                                     event_type=event_type, round=round,
                                     artifact_refs=(LEDGER_FILENAME,), details=details, actor_type=actor)

        def developer(**kwargs: Any) -> Any:
            run = kwargs["run"]
            policy = GuardrailPolicy(allowed_roots=[run["worktree"]], read_only=False,
                                     tool_whitelist=list(DEVELOPER_TOOL_WHITELIST))
            run_context = RunExecutionContext(run_id=run["run_id"], worktree=run["worktree"], branch=run["branch"])
            bound_spec, bound_prompt = _bind_agent_inputs(
                kwargs["ticket_spec"], kwargs["prompt"], repository=repository, worktree=run["worktree"],
            )
            inputs = {"ticket_spec": bound_spec, "findings": kwargs["findings"]}
            process_observer = ProcessOutputStore(
                run["artifact_dir"], known_secrets=secret_values,
            ).observer(stage="development", role="developer", round=int(kwargs.get("qa_attempt") or 0))

            def call(session: dict[str, Any] | None) -> Any:
                agent = catalog.build_agent(
                    developer_profile, role="developer", cwd=run["worktree"],
                    allowed_roots=[run["worktree"]],
                    system=bound_prompt + "\nDo not run git commit.",
                    session=session,
                )
                agent = {**agent, "process_observer": process_observer}
                return drivers.cli_call(agent, inputs, {"agent": "developer"}, str(repository),
                                        policy=policy, run_context=run_context)

            ledger = SessionLedger(run["artifact_dir"])
            provider = developer_profile["provider"]
            base_entry = {"role": "developer", "provider": provider,
                          "model": developer_profile.get("model", ""),
                          "sandbox": run["worktree"], "permission_mode": "write"}
            stored = ledger.get("developer")
            if stored is None:
                # First attempt: open the role's persistent session.
                if provider == "codex":
                    output = call({"mode": "new"})
                    session_id = parse_codex_session_id(output)
                    entry = ledger.record("developer", {**base_entry, "mode": "new", "session_id": session_id})
                    if session_id:
                        session_event(run, stage="development", role="developer", status="ACTIVE",
                                      event_type="agent_session_started", details=entry)
                    else:
                        session_event(run, stage="development", role="developer", status="DEGRADED",
                                      event_type="session_resume_unavailable",
                                      details={**entry, "reason": "codex --json output carried no parseable session id; later attempts run fresh with findings handover"})
                    return output
                session_id = str(uuid.uuid4())
                entry = ledger.record("developer", {**base_entry, "mode": "new", "session_id": session_id})
                session_event(run, stage="development", role="developer", status="ACTIVE",
                              event_type="agent_session_started", details=entry)
                return call({"mode": "new", "session_id": session_id})

            session_id = stored.get("session_id")
            if not session_id:
                # Recorded degradation: fresh session, findings travel in inputs.
                return call({"mode": "ephemeral"})
            try:
                return call({"mode": "resume", "session_id": session_id})
            except Exception as exc:
                ledger.record("developer", {**stored, "session_id": None, "mode": "degraded"})
                session_event(run, stage="development", role="developer", status="DEGRADED",
                              event_type="session_resume_failed",
                              details={**base_entry, "session_id": session_id,
                                       "reason": (str(exc) or type(exc).__name__)[:300],
                                       "recovery": "one fresh retry with findings handover"})
                return call({"mode": "ephemeral"})

        def checker(run, *, qa_attempt: int) -> dict[str, Any]:
            spec = json.loads((Path(run.artifact_dir) / "ticket-spec.json").read_text(encoding="utf-8"))
            commands = _verification_commands(spec)
            verification_environment = _verification_environment(repository)
            output = ProcessOutputStore(run.artifact_dir, known_secrets=secret_values)
            checks = []
            for command in commands:
                started_at = datetime.now(timezone.utc).isoformat()
                output.append(stage="verification", role="controller", stream="process",
                              message=f"started command={command}", round=qa_attempt)
                proc = subprocess.run(["/bin/sh", "-c", command], cwd=run.worktree, capture_output=True,
                                      text=True, stdin=subprocess.DEVNULL, timeout=60, check=False,
                                      env=verification_environment)
                checks.append({
                    "command": command,
                    "cwd": run.worktree,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                })
                if proc.stdout:
                    output.append(stage="verification", role="controller", stream="stdout",
                                  message=proc.stdout, round=qa_attempt)
                if proc.stderr:
                    output.append(stage="verification", role="controller", stream="stderr",
                                  message=proc.stderr, round=qa_attempt)
                output.append(stage="verification", role="controller", stream="process",
                              message=f"exited code={proc.returncode} command={command}", round=qa_attempt)
            diff_proc = subprocess.run(["git", "diff", "--no-ext-diff", run.base_sha], cwd=run.worktree,
                                       capture_output=True, text=True, check=False)
            files_proc = subprocess.run(["git", "diff", "--name-only", run.base_sha], cwd=run.worktree,
                                        capture_output=True, text=True, check=False)
            untracked_proc = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=run.worktree,
                                             capture_output=True, text=True, check=False)
            head_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=run.worktree,
                                       capture_output=True, text=True, check=False)
            changed_files = [line for line in files_proc.stdout.splitlines() if line]
            diff_parts = [diff_proc.stdout]
            for path in (line for line in untracked_proc.stdout.splitlines() if line):
                # ``--no-index`` returns 1 for a real textual difference.
                untracked_diff = subprocess.run(["git", "diff", "--no-index", "--", "/dev/null", path], cwd=run.worktree,
                                                capture_output=True, text=True, check=False)
                if untracked_diff.returncode not in {0, 1}:
                    return {"verified": False, "checks": checks, "changed_files": changed_files,
                            "diff": "", "qa_attempt": qa_attempt}
                changed_files.append(path)
                diff_parts.append(untracked_diff.stdout)
            provenance = {
                "phase": "pre_commit_qa",
                "commit_policy": "Controller creates the ticket commit only after QA PASS",
                "worktree": run.worktree,
                "branch": run.branch,
                "base_sha": run.base_sha,
                "head_sha": head_proc.stdout.strip() if head_proc.returncode == 0 else None,
                "pre_existing_dirty_paths": [],
                "current_changed_files": changed_files,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            return {"verified": diff_proc.returncode == 0 and files_proc.returncode == 0 and untracked_proc.returncode == 0
                                and head_proc.returncode == 0
                                and bool(changed_files) and all(item["exit_code"] == 0 for item in checks),
                    "checks": checks, "changed_files": changed_files, "diff": "".join(diff_parts),
                    "provenance": provenance, "qa_attempt": qa_attempt}

        def independent_qa(**kwargs: Any) -> Any:
            run = kwargs["run"]
            bound_spec, bound_prompt = _bind_agent_inputs(
                kwargs["ticket_spec"], kwargs["prompt"], repository=repository, worktree=run["worktree"],
            )
            agent = catalog.build_agent(
                qa_profile, role="qa", cwd=run["worktree"], allowed_roots=[run["worktree"]],
                system=qa.QA_SYSTEM_PROMPT, expect="json", session={"mode": "ephemeral"},
            )
            agent = {**agent, "process_observer": ProcessOutputStore(
                run["artifact_dir"], known_secrets=secret_values,
            ).observer(stage="qa", role="qa", round=kwargs["qa_attempt"])}
            entry = SessionLedger(run["artifact_dir"]).record("qa", {
                "role": "qa", "provider": qa_profile["provider"], "model": qa_profile.get("model", ""),
                "sandbox": run["worktree"], "permission_mode": "read-only",
                "mode": "ephemeral", "session_id": None, "qa_attempt": kwargs["qa_attempt"],
            })
            session_event(run, stage="qa", role="qa", status="ACTIVE",
                          event_type="agent_session_started", details=entry, round=kwargs["qa_attempt"])
            return qa.run_qa(agent=agent, engine_root=str(repository), ticket_spec=bound_spec,
                             diff=kwargs["diff"], test_evidence=kwargs["verification_evidence"],
                             run_id=run["run_id"], qa_attempt=kwargs["qa_attempt"],
                             ticket_context=bound_prompt)

        return WebAgentLoop(
            run_manager, developer=developer, checker=checker,
            qa=independent_qa, known_secrets=secret_values,
        )

    def timeline(self, run_id: str) -> dict[str, Any]:
        return self._loop_for(run_id).timeline(run_id)

    def latest_timeline(self) -> dict[str, Any]:
        run_root = self.repository / ".ticket-autopilot" / "runs"
        candidates = list(run_root.glob("*/state.json")) if run_root.is_dir() else []
        if not candidates:
            return {"run_id": None, "snapshot": None, "events": [], "process_output": []}
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        return self.timeline(latest.parent.name)

    def retry(self, run_id: str) -> dict[str, Any]:
        return self._loop_for(run_id).retry_current_stage(run_id)

    def stop_run(self, run_id: str) -> dict[str, Any]:
        return self._loop_for(run_id).stop(run_id)

    def owner_action(self, run_id: str, authorization: dict[str, Any]) -> dict[str, Any]:
        return self._loop_for(run_id).record_owner_action(run_id, authorization)

    def _loop_for(self, run_id: str) -> WebAgentLoop:
        if run_id in self._web_loops:
            return self._web_loops[run_id]
        # A reopened browser reads artifacts without reviving or guessing a process.
        secret_values = (self.settings.load(redacted=False)["plane"].get("api_key", ""),)
        unavailable = lambda **_kwargs: (_ for _ in ()).throw(WebAgentLoopError("execution context is unavailable"))
        return WebAgentLoop(RunManager(self.repository, known_secrets=secret_values), developer=unavailable,
                            checker=unavailable, qa=unavailable, known_secrets=secret_values)

    def _summary(self, item: dict[str, Any]) -> dict[str, Any]:
        detail = self._detail(item)
        return {key: detail[key] for key in (
            "id", "identifier", "title", "state", "priority", "risk", "eligible", "reason", "prompt_availability",
        )}

    def _detail(self, item: dict[str, Any]) -> dict[str, Any]:
        # Owner-approved relaxed intake: nine-field template tickets may omit
        # operational parameters, which default from local configuration.
        preflight = preflight_plane_issue(item, defaults={
            "repository": self.settings.load(redacted=True).get("repository") or "",
        })
        readiness = readiness_errors(item) if preflight["status"] == "READY" else []
        unfinished = plane.is_unfinished_work_item(item)
        project_matches = self._project_matches(item)
        eligible = unfinished and project_matches and preflight["status"] == "READY" and not readiness
        reason = None
        if not unfinished:
            reason = f"Plane state group {item['state']['group']} is not eligible for a Run"
        elif not project_matches:
            reason = "expanded Plane project does not match the configured project"
        elif readiness:
            reason = "; ".join(readiness)
        elif not eligible:
            reason = "; ".join(error["message"] for error in preflight["errors"])
        resolver = PromptResolver(self.repository)
        return {
            "id": str(item["id"]), "identifier": item["identifier"],
            "title": item.get("name") or item.get("title"), "state": item["state"],
            "priority": item.get("priority"),
            "risk": (preflight.get("ticket_spec") or {}).get("risk_tier"),
            "eligible": eligible, "reason": reason,
            "prompt_availability": resolver.availability(item["identifier"]),
            "ticket_spec": preflight.get("ticket_spec"),
        }

    def _project_matches(self, item: dict[str, Any]) -> bool:
        # The endpoint is already scoped to the configured project.  When Plane
        # expands project.id as well, retain that second deterministic check.
        expected = self.settings.load(redacted=False)["plane"]["project"]
        project = item.get("project")
        actual = project.get("id") if isinstance(project, dict) else None
        return actual is None or str(actual) == expected

    def _plane_options(self) -> dict[str, str]:
        config = self.settings.load(redacted=False)["plane"]
        required = ("workspace", "project", "api_key")
        if any(not config.get(key) for key in required):
            raise plane.PlaneAPIError("Plane workspace, project, and API key must be configured locally")
        return {"workspace": config["workspace"], "project_id": config["project"], "api_key": config["api_key"]}


class SettingsHandler(BaseHTTPRequestHandler):
    """Small same-origin JSON API and static settings page."""

    server_version = "TicketAutopilot/0.1"

    @property
    def settings(self) -> LocalConfig:
        return self.server.settings  # type: ignore[attr-defined]

    @property
    def service_id(self) -> str:
        return self.server.service_id  # type: ignore[attr-defined]

    @property
    def catalog(self) -> AgentCatalog:
        catalog = getattr(self.server, "agent_catalog", None)
        if catalog is None:
            catalog = AgentCatalog()
            self.server.agent_catalog = catalog  # type: ignore[attr-defined]
        return catalog

    @property
    def tickets(self) -> TicketBoard:
        board = getattr(self.server, "ticket_board", None)
        if board is None:
            board = TicketBoard(self.settings, repository=getattr(self.server, "project_root", Path.cwd()),
                                planner=getattr(self.server, "planner_adapter", None),
                                web_loop_factory=getattr(self.server, "web_loop_factory", None),
                                catalog=self.catalog)
            self.server.ticket_board = board  # type: ignore[attr-defined]
        return board

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"status": "ok", "service_id": self.service_id})
            elif path == "/api/config":
                self._json(HTTPStatus.OK, self.settings.load(redacted=True))
            elif path == "/api/agent-catalog":
                refresh = "refresh=1" in (parsed.query or "")
                self._json(HTTPStatus.OK, self.catalog.snapshot(refresh=refresh))
            elif path == "/api/tickets":
                self._json(HTTPStatus.OK, self.tickets.list())
            elif path == "/api/runs/latest":
                self._json(HTTPStatus.OK, self.tickets.latest_timeline())
            elif path.startswith("/api/operations/"):
                operation_id = path.removeprefix("/api/operations/").rstrip("/")
                self._json(HTTPStatus.OK, self.tickets.operation(operation_id))
            elif path.startswith("/api/runs/"):
                run_id = path.removeprefix("/api/runs/").rstrip("/")
                self._json(HTTPStatus.OK, self.tickets.timeline(run_id))
            elif path.startswith("/api/tickets/"):
                issue_id = path.removeprefix("/api/tickets/")
                self._json(HTTPStatus.OK, self.tickets.detail(issue_id))
            elif path in ("/", "/index.html"):
                self._static("index.html", "text/html; charset=utf-8")
            elif path == "/app.js":
                self._static("app.js", "application/javascript; charset=utf-8")
            elif path == "/styles.css":
                self._static("styles.css", "text/css; charset=utf-8")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (plane.PlaneAPIError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/runs/"):
            remainder = path.removeprefix("/api/runs/").strip("/")
            run_id, separator, action = remainder.partition("/")
            try:
                if separator and action == "retry":
                    self._json(HTTPStatus.OK, self.tickets.retry(run_id))
                elif separator and action == "stop":
                    self._json(HTTPStatus.OK, self.tickets.stop_run(run_id))
                elif separator and action == "owner-actions":
                    self._json(HTTPStatus.OK, self.tickets.owner_action(run_id, self._request_json()))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, WebAgentLoopError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path.startswith("/api/tickets/") and path.endswith("/run"):
            issue_id = path.removeprefix("/api/tickets/").removesuffix("/run").rstrip("/")
            try:
                self._json(HTTPStatus.OK, self.tickets.start_run(issue_id))
            except (plane.PlaneAPIError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "developer_calls": 0, "qa_calls": 0})
            return
        if path.startswith("/api/tickets/") and path.endswith("/prepare"):
            issue_id = path.removeprefix("/api/tickets/").removesuffix("/prepare").rstrip("/")
            try:
                self._json(HTTPStatus.OK, self.tickets.prepare(issue_id))
            except (plane.PlaneAPIError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "developer_calls": 0, "qa_calls": 0})
            return
        if path != "/api/config":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 64 * 1024:
                raise LocalServiceError("settings request is invalid")
            value = self._request_json()
            self._json(HTTPStatus.OK, self.settings.save(value))
        except (CatalogError, LocalServiceError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "invalid settings"})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid settings"})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "could not save settings"})

    def _request_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 64 * 1024:
            raise LocalServiceError("request is invalid")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise LocalServiceError("request is invalid")
        return value

    def _static(self, name: str, content_type: str) -> None:
        path = Path(__file__).with_name("static") / name
        try:
            body = path.read_bytes()
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "settings page unavailable"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(redact(value), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        # Never log request bodies or exception details; config may contain an API key.
        return


def serve(*, port: int, service_id: str, home: str | Path | None = None) -> None:
    """Run the localhost-only HTTP server in the foreground."""
    server = ThreadingHTTPServer((HOST, port), SettingsHandler)
    catalog = AgentCatalog()
    server.agent_catalog = catalog  # type: ignore[attr-defined]
    server.settings = LocalConfig(home, agent_profile_validator=catalog.validate_profile)  # type: ignore[attr-defined]
    server.service_id = service_id  # type: ignore[attr-defined]
    server.project_root = Path(os.environ.get("TICKET_AUTOPILOT_PROJECT_ROOT") or Path.cwd()).resolve()  # type: ignore[attr-defined]
    server.serve_forever(poll_interval=0.2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="start-ticket-autopilot")
    parser.add_argument("command", nargs="?", choices=("start", "status", "stop", "restart", "server"), default="start")
    parser.add_argument("--port", type=int, default=PORT, help=argparse.SUPPRESS)
    parser.add_argument("--service-id", help=argparse.SUPPRESS)
    parser.add_argument("--home", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 2
    if args.command == "server":
        if not args.service_id:
            print("Server identity is required.", file=sys.stderr)
            return 2
        serve(port=args.port, service_id=args.service_id, home=args.home)
        return 0
    manager = ServiceManager(port=args.port)
    if args.command == "start":
        return manager.start()
    if args.command == "status":
        return manager.status()
    if args.command == "stop":
        return manager.stop()
    return manager.restart()


if __name__ == "__main__":
    raise SystemExit(main())

"""Local-only settings server and lifecycle manager for Ticket Autopilot.

This module intentionally does not invoke the ticket controller, Plane, or an
Agent.  It supplies only the persistent local entrypoint that those later
features can reuse.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlparse

from ticket_autopilot.connectors import plane
from ticket_autopilot.services.prompt_resolver import PromptPreparationError, PromptResolver
from ticket_autopilot.services.ticket_contract import preflight_plane_issue, readiness_errors
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
    "agents": {"planner": "", "developer": "", "qa": ""},
}
_SECRET_MARKERS = ("api_key", "secret", "token", "password", "credential")


class LocalServiceError(RuntimeError):
    """A local service operation could not be completed safely."""


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


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

    def __init__(self, home: str | Path | None = None):
        self.home = app_home(home)
        self.path = self.home / CONFIG_FILENAME
        _private_directory(self.home)

    def load(self, *, redacted: bool = True) -> dict[str, Any]:
        stored = _read_json(self.path) or {}
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
        atomic_json_write(self.path, updated)
        return redact_secrets(updated)

    @staticmethod
    def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                LocalConfig._merge(target[key], value)
            elif key in target and isinstance(value, str):
                target[key] = value

    @staticmethod
    def _merge_allowed(target: dict[str, Any], incoming: dict[str, Any]) -> None:
        for key in ("repository",):
            if key in incoming:
                if not isinstance(incoming[key], str):
                    raise LocalServiceError(f"{key} must be a string")
                target[key] = incoming[key]
        for section, keys in (("plane", ("workspace", "project", "api_key")),
                              ("agents", ("planner", "developer", "qa"))):
            if section not in incoming:
                continue
            supplied = incoming[section]
            if not isinstance(supplied, dict):
                raise LocalServiceError(f"{section} must be an object")
            for key in keys:
                if key in supplied:
                    if not isinstance(supplied[key], str):
                        raise LocalServiceError(f"{section}.{key} must be a string")
                    # A settings page sends the displayed mask back unchanged;
                    # that must not overwrite a real saved credential.
                    if section == "plane" and key == "api_key" and supplied[key] == MASK:
                        continue
                    target[section][key] = supplied[key]


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
            "--port", str(self.port), "--service-id", service_id,
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

    def __init__(self, settings: LocalConfig, *, repository: str | Path | None = None, planner: Callable[..., dict[str, str]] | None = None):
        self.settings = settings
        self.repository = Path(repository or Path.cwd()).resolve()
        self.planner = planner

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

    def _summary(self, item: dict[str, Any]) -> dict[str, Any]:
        detail = self._detail(item)
        return {key: detail[key] for key in (
            "id", "identifier", "title", "state", "priority", "risk", "eligible", "reason", "prompt_availability",
        )}

    def _detail(self, item: dict[str, Any]) -> dict[str, Any]:
        preflight = preflight_plane_issue(item)
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
    def tickets(self) -> TicketBoard:
        board = getattr(self.server, "ticket_board", None)
        if board is None:
            board = TicketBoard(self.settings, repository=getattr(self.server, "project_root", Path.cwd()),
                                planner=getattr(self.server, "planner_adapter", None))
            self.server.ticket_board = board  # type: ignore[attr-defined]
        return board

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"status": "ok", "service_id": self.service_id})
            elif path == "/api/config":
                self._json(HTTPStatus.OK, self.settings.load(redacted=True))
            elif path == "/api/tickets":
                self._json(HTTPStatus.OK, self.tickets.list())
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
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise LocalServiceError("settings request is invalid")
            self._json(HTTPStatus.OK, self.settings.save(value))
        except (ValueError, UnicodeDecodeError, LocalServiceError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid settings"})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "could not save settings"})

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
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
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
    server.settings = LocalConfig(home)  # type: ignore[attr-defined]
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

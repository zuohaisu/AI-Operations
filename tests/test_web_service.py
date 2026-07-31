"""AIO-17 localhost lifecycle tests using only temporary state and ports."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ticket_autopilot.services.agent_catalog import AgentCatalog
from ticket_autopilot.web import HOST, LocalConfig, ServiceManager, SettingsHandler, atomic_json_write


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((HOST, 0))
        return int(candidate.getsockname()[1])


@pytest.fixture
def service(tmp_path: Path):
    opened: list[str] = []
    manager = ServiceManager(
        home=tmp_path / ".ticket-autopilot", port=_free_port(), project_root=Path.cwd(),
        browser_opener=opened.append,
    )
    yield manager, opened
    manager.stop()


def test_start_is_detached_healthy_and_single_instance(service: tuple[ServiceManager, list[str]]) -> None:
    manager, opened = service
    assert manager.start() == 0
    record = json.loads(manager.service_path.read_text())
    with urlopen(f"http://{HOST}:{manager.port}/api/health", timeout=1) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok", "service_id": record["service_id"]}
    payload = json.dumps({"plane": {"workspace": "hspace", "api_key": "server-secret"}}).encode()
    request = Request(f"http://{HOST}:{manager.port}/api/config", data=payload, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=1) as response:
        assert json.loads(response.read())["plane"]["api_key"] == "********"
    with urlopen(f"http://{HOST}:{manager.port}/api/config", timeout=1) as response:
        assert b"server-secret" not in response.read()
    assert b"server-secret" not in manager.log_path.read_bytes()
    assert manager.status() == 0

    assert manager.start() == 0
    assert json.loads(manager.service_path.read_text())["pid"] == record["pid"]
    assert opened == [manager.url, manager.url]
    assert manager.stop() == 0
    assert manager.status() == 1
    assert manager.log_path.exists()


def test_stale_record_recovers_but_foreign_listener_is_never_stopped(tmp_path: Path) -> None:
    port = _free_port()
    manager = ServiceManager(home=tmp_path / ".ticket-autopilot", port=port, project_root=Path.cwd(), browser_opener=lambda _url: None)
    atomic_json_write(manager.service_path, {
        "schema_version": 1, "pid": 999999, "process_group": 999999,
        "host": HOST, "port": port, "service_id": "x" * 32,
    })
    assert manager.start() == 0
    assert manager.stop() == 0

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as foreign:
        foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        foreign.bind((HOST, port))
        foreign.listen()
        assert manager.start(open_browser=False) == 1
        assert foreign.fileno() != -1


@pytest.fixture
def catalog_server(tmp_path: Path):
    def fake_runner(cmd, **_kwargs):
        outputs = {
            ("qodercli", "--version"): "1.1.9 (Qoder CLI)\n",
            ("qodercli", "--list-models"): "MODEL\nUltimate\n",
        }
        stdout = outputs.get(tuple(cmd))
        return subprocess.CompletedProcess(cmd, 0 if stdout is not None else 1, stdout=stdout or "", stderr="")

    catalog = AgentCatalog(
        runner=fake_runner,
        which=lambda command: "/usr/local/bin/qodercli" if command == "qodercli" else None,
        codex_config_path=tmp_path / "missing-codex.toml",
    )
    server = ThreadingHTTPServer((HOST, 0), SettingsHandler)
    server.agent_catalog = catalog
    server.settings = LocalConfig(tmp_path / ".ticket-autopilot", agent_profile_validator=catalog.validate_profile)
    server.service_id = "t" * 32
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://{HOST}:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_agent_catalog_endpoint_reports_probed_availability(catalog_server: str) -> None:
    with urlopen(f"{catalog_server}/api/agent-catalog", timeout=2) as response:
        providers = json.loads(response.read())["providers"]
    assert set(providers) == {"codex", "claude", "qodercli"}
    assert providers["qodercli"]["available"] is True
    assert providers["qodercli"]["models"] == ["Ultimate"]
    assert providers["codex"]["available"] is False
    assert providers["codex"]["reason"]
    with urlopen(f"{catalog_server}/api/agent-catalog?refresh=1", timeout=2) as response:
        assert json.loads(response.read())["providers"]["claude"]["available"] is False


def test_config_post_rejects_profiles_outside_the_probed_catalog(catalog_server: str) -> None:
    def post(agents: dict) -> tuple[int, dict]:
        payload = json.dumps({"agents": agents}).encode()
        request = Request(f"{catalog_server}/api/config", data=payload, method="POST",
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    status, body = post({"qa": {"provider": "codex", "model": "", "reasoning": ""}})
    assert status == 400 and "unavailable" in body["error"]
    status, body = post({"qa": {"provider": "qodercli", "model": "not-probed", "reasoning": ""}})
    assert status == 400 and "not in the probed catalog" in body["error"]
    status, body = post({"qa": {"provider": "qodercli", "model": "Ultimate", "reasoning": ""}})
    assert status == 200 and body["agents"]["qa"]["model"] == "Ultimate"
    with urlopen(f"{catalog_server}/api/config", timeout=2) as response:
        assert json.loads(response.read())["agents"]["qa"]["provider"] == "qodercli"


def test_static_settings_ui_exposes_three_agent_dropdown_groups() -> None:
    static = Path(__file__).resolve().parents[1] / "src" / "ticket_autopilot" / "static"
    index = (static / "index.html").read_text(encoding="utf-8")
    for role in ("planner", "developer", "qa"):
        for field in ("provider", "model", "reasoning", "permission_mode"):
            assert f'<select name="{role}-{field}">' in index
        assert f'id="{role}-agent-status"' in index
    app = (static / "app.js").read_text(encoding="utf-8")
    assert "/api/agent-catalog" in app
    assert "refresh=1" in app
    assert "not in the probed catalog" in app

"""AIO-17 localhost lifecycle tests using only temporary state and ports."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from urllib.request import Request, urlopen

import pytest

from ticket_autopilot.web import HOST, ServiceManager, atomic_json_write


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

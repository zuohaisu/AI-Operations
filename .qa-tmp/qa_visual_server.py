"""AIO-18 QA visual sandbox: real Web UI + fake local Plane, all state in .qa-tmp.

Read-only for the repository: canonical AIO-018 prompts are COPIED into a
sandbox repo; the product web server runs on 127.0.0.1:8788 (not the AIO-17
serial resource 8765) with project_root inside .qa-tmp.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ticket_autopilot.connectors import plane  # noqa: E402
from ticket_autopilot import web  # noqa: E402

QA_ROOT = REPO / ".qa-tmp" / "aio18-visual"
FAKE_PLANE_PORT = 8799
WEB_PORT = 8788
PROJECT_ID = "qa-project"

CONTRACT_HTML = """<h2>Goal</h2><p>deterministic intake</p><h2>Scope</h2><ul><li>Impact closure covers callers and consumers, triggered guards, executable dependencies, Given when then behavioral AC, observed checked-at semantic mapping, and global serial resource 127.0.0.1:8765.</li></ul>
<h2>Out-of-scope</h2><ul><li>no PR</li></ul><h2>Risk Tier</h2><p>R1</p><h2>Acceptance Criteria</h2><ul><li>AC-1: works</li></ul>
<h2>Verification</h2><ul><li>AC-1: automated: <code>pytest -q</code></li></ul><h2>Repository</h2><p><code>zuohaisu/AI-Operations</code></p>
<h2>Required Checks</h2><ul><li><code>pytest -q</code></li></ul><h2>Constraints</h2><ul><li>max_fix_attempts: 0</li><li>allow_main_push: false</li></ul>"""


def item(sequence: int, group: str, name: str, *, html: str = CONTRACT_HTML, priority: str = "high") -> dict:
    return {
        "id": f"qa-item-{sequence}", "name": name, "description": None, "identifier": None,
        "description_html": html, "description_stripped": "flat preview", "sequence_id": sequence,
        "project": {"identifier": "AIO"}, "priority": priority,
        "state": {"id": f"{group}-state-id", "group": group, "name": group.title()},
    }


ITEMS = [
    item(16, "backlog", "Backlog ticket with an intentionally very long title to check for truncation, wrapping, and overflow behaviour in the unfinished ticket panel of the AIO-18 web board"),
    item(17, "unstarted", "Unstarted ticket"),
    item(18, "started", "AIO-18 ticket with existing canonical prompts"),
    item(19, "started", "Ticket whose prompts are missing (Planner hard break demo)"),
    item(22, "started", "Ticket failing readiness evidence (ineligible)",
         html=CONTRACT_HTML.replace("Impact closure", "closure")),
    item(20, "completed", "Completed ticket (must not be listed)"),
    item(21, "cancelled", "Cancelled ticket (must not be listed)"),
]


class FakePlane(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        prefix = f"/api/v1/workspaces/hspace/projects/{PROJECT_ID}/work-items/"
        if path == prefix:
            body = {"results": ITEMS}
        elif path.startswith(prefix):
            wanted = path[len(prefix):].strip("/")
            matches = [entry for entry in ITEMS if entry["id"] == wanted]
            if not matches:
                self.send_error(404)
                return
            body = matches[0]
        else:
            self.send_error(404)
            return
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):  # quiet
        return


def main() -> None:
    shutil.rmtree(QA_ROOT, ignore_errors=True)
    sandbox_repo = QA_ROOT / "repo"
    tasks = sandbox_repo / "tasks"
    tasks.mkdir(parents=True)
    for name in ("AIO-018-dev-prompt.md", "AIO-018-acceptance-prompt.md"):
        shutil.copyfile(REPO / "tasks" / name, tasks / name)

    home = QA_ROOT / "home"
    settings = web.LocalConfig(home)
    settings.save({"plane": {"workspace": "hspace", "project": PROJECT_ID, "api_key": "qa-fake-key"},
                   "repository": "zuohaisu/AI-Operations"})

    plane.PLANE_API_ROOT = f"http://127.0.0.1:{FAKE_PLANE_PORT}/api/v1"
    plane._rate_limit = lambda: None

    fake = ThreadingHTTPServer(("127.0.0.1", FAKE_PLANE_PORT), FakePlane)
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), web.SettingsHandler)
    server.settings = settings
    server.service_id = "qa-visual-session"
    server.project_root = sandbox_repo
    server.planner_adapter = None  # missing prompts must hard-break, never spawn an Agent
    print(f"QA visual sandbox ready: http://127.0.0.1:{WEB_PORT}/  (fake Plane on {FAKE_PLANE_PORT})", flush=True)
    server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()

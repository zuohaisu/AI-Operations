"""Unit tests for the parameterized Plane connector (all network is mocked)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from ticket_autopilot.connectors import plane
from ticket_autopilot.engine.engine import Engine
from ticket_autopilot.engine.handlers import close_ticket as close_handler


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PlaneConnectorTests(unittest.TestCase):
    def test_fetch_issue_uses_parameterized_project_browser_ua_and_key(self):
        plane._last_request_at = None
        payload = {"id": "issue-1", "name": "AIO-8", "description": None, "identifier": None,
                   "description_html": "<h2>Goal</h2><ul><li>keep structure</li></ul><pre><code>pytest -q</code></pre>",
                   "description_stripped": "keep structure", "sequence_id": 8,
                   "project": {"identifier": "AIO"}, "state": {"id": "state-1", "group": "started"}}
        with mock.patch("ticket_autopilot.connectors.plane.urllib.request.urlopen",
                        return_value=FakeResponse(payload)) as open_url:
            issue = plane.fetch_issue("issue-1", workspace="team", project_id="project-9", api_key="secret")

        self.assertEqual(issue["identifier"], "AIO-8")
        self.assertIn("## Goal", issue["description"])
        self.assertIn("- keep structure", issue["description"])
        self.assertIn("```", issue["description"])
        self.assertEqual(issue["raw_source"]["description"], None)
        request = open_url.call_args.args[0]
        self.assertIn("/workspaces/team/projects/project-9/work-items/issue-1/?expand=state,project", request.full_url)
        self.assertEqual(request.get_header("X-api-key"), "secret")
        self.assertEqual(request.get_header("User-agent"), plane.BROWSER_UA)

    def test_build_workflow_is_engine_valid_and_contains_ticket_context(self):
        issue = {
            "id": "ad9c6997-55f0-4c0b-9e19-330e3cf27997",
            "sequence_id": 8,
            "name": "Implement Ticket/PR connector",
            "description": "## Goal\nPlane to YAML\n\n## Acceptance\n- [ ] mock run succeeds",
            "state": "in-progress-state",
        }
        workflow = plane.build_workflow_yaml(issue)

        self.assertEqual(workflow["version"], "1.0")
        self.assertEqual(workflow["name"], "ticket-ad9c6997-55f0-4c0b-9e19-330e3cf27997")
        self.assertEqual(workflow["vars"]["max_retries"], 5)
        self.assertEqual(workflow["vars"]["ticket"]["description"], issue["description"])
        self.assertEqual(workflow["params"]["ticket_id"]["default"], issue["id"])
        self.assertEqual({node["id"] for node in workflow["nodes"]}, {"plan", "execute", "verify", "close"})
        self.assertTrue(any(edge.get("kind") == "loop" and edge["from"] == "verify"
                            and edge["to"] == "execute" for edge in workflow["edges"]))

        run = Engine(workflow, mock=True).run({"ticket_id": issue["id"]})
        self.assertEqual(run["not_completed"], [])
        self.assertIn("close", run["completed"])

    def test_engine_closer_delegates_to_parameterized_connector(self):
        with mock.patch.object(close_handler, "close_plane_ticket", return_value={"closed": True}) as close:
            result = close_handler.close_ticket("issue-1", "plan", "result")

        self.assertEqual(result, {"closed": True})
        close.assert_called_once_with("issue-1", "## Plan\nplan\n\n## Execute result\nresult\n")

    def test_set_ticket_state_supports_in_review_without_done_semantics(self):
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("body")))
            if path.endswith("/comments/"):
                return 201, {"id": "comment-1"}
            if path.endswith("/states/"):
                return 200, {"results": [{"id": "review-uuid", "name": "In Review"}]}
            return 200, {"id": "issue-1", "state": "review-uuid"}

        with mock.patch("ticket_autopilot.connectors.plane._request", side_effect=request):
            result = plane.set_ticket_state(
                "issue-1", "In Review", "PR/Run/Checks/QA evidence",
                workspace="hspace", project_id="aio-project", api_key="secret",
            )

        self.assertTrue(result["updated"])
        self.assertEqual(result["state_name"], "In Review")
        self.assertEqual([call[0] for call in calls], ["POST", "GET", "PATCH"])
        self.assertEqual(calls[-1][2], {"state": "review-uuid"})

    def test_close_ticket_comments_then_uses_project_done_state_and_state_field(self):
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("body")))
            if path.endswith("/comments/"):
                return 201, {"id": "comment-1"}
            if path.endswith("/states/"):
                return 200, {"results": [{"id": "done-uuid", "name": "Done"}]}
            self.assertEqual(method, "PATCH")
            return 200, {"id": "issue-1", "state": "done-uuid"}

        with mock.patch("ticket_autopilot.connectors.plane._request", side_effect=request):
            result = plane.close_ticket("issue-1", "Closed after <verification>",
                                        workspace="hspace", project_id="aio-project", api_key="secret")

        self.assertTrue(result["closed"])
        self.assertEqual([call[0] for call in calls], ["POST", "GET", "PATCH"])
        self.assertEqual(calls[-1][1], "/projects/aio-project/issues/issue-1/")
        self.assertEqual(calls[-1][2], {"state": "done-uuid"})
        self.assertNotIn("state_id", calls[-1][2])
        self.assertIn("&lt;verification&gt;", calls[0][2]["comment_html"])


if __name__ == "__main__":
    unittest.main()

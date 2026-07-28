"""Unit tests for the GitHub PR connector (all network is mocked)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from ticket_autopilot.connectors import github


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GitHubConnectorTests(unittest.TestCase):
    def test_create_pr_rejects_base_or_main_as_head_before_network_call(self):
        for head in ("main", "fork:main"):
            with self.subTest(head=head), self.assertRaisesRegex(ValueError, "separate feature branch"):
                github.create_pr(repo="org/repo", base="main", head=head,
                                  title="AIO-8", body="", token="token")

    def test_create_pr_posts_reviewable_feature_branch_metadata(self):
        response = {"number": 42, "html_url": "https://github.com/org/repo/pull/42", "draft": True}
        with mock.patch("ticket_autopilot.connectors.github.urllib.request.urlopen",
                        return_value=FakeResponse(response)) as open_url:
            result = github.create_pr(repo="org/repo", base="main", head="feature/aio-8",
                                      title="AIO-8: connector", body="Verification passed", token="token")

        self.assertEqual(result["number"], 42)
        self.assertEqual(result["url"], "https://github.com/org/repo/pull/42")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/org/repo/pulls")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(json.loads(request.data), {
            "title": "AIO-8: connector", "body": "Verification passed",
            "base": "main", "head": "feature/aio-8", "draft": True,
        })


if __name__ == "__main__":
    unittest.main()

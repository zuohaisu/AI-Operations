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
    @staticmethod
    def authorization(action="merge"):
        return {
            "actor": "repo-owner",
            "actor_type": "repository_owner",
            "action": action,
            "approved": True,
            "approved_at": "2026-07-31T00:00:00+08:00",
            "reason": "owner selected the delivery action",
        }

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

    def test_merge_pr_rejects_missing_or_agent_authorization_before_network(self):
        invalid = self.authorization()
        invalid["actor_type"] = "developer_agent"
        for authorization in (None, invalid):
            with self.subTest(authorization=authorization), self.assertRaisesRegex(
                ValueError, "repository.owner authorization|repository_owner"
            ), mock.patch(
                "ticket_autopilot.connectors.github.urllib.request.urlopen"
            ) as open_url:
                github.merge_pr(
                    repo="org/repo",
                    pull_number=42,
                    authorization=authorization,
                    token="token",
                )
                open_url.assert_not_called()

    def test_merge_pr_uses_explicit_owner_authorization_and_returns_audit(self):
        response = {"sha": "abc123", "merged": True, "message": "Pull Request successfully merged"}
        with mock.patch(
            "ticket_autopilot.connectors.github.urllib.request.urlopen",
            return_value=FakeResponse(response),
        ) as open_url:
            result = github.merge_pr(
                repo="org/repo",
                pull_number=42,
                authorization=self.authorization(),
                merge_method="squash",
                commit_title="AIO-18: ticket panel",
                token="token",
            )

        self.assertTrue(result["merged"])
        self.assertEqual(result["authorization"]["actor"], "repo-owner")
        request = open_url.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/org/repo/pulls/42/merge",
        )
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(json.loads(request.data), {
            "merge_method": "squash",
            "commit_title": "AIO-18: ticket panel",
        })


if __name__ == "__main__":
    unittest.main()

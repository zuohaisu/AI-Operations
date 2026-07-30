"""AIO-11 evidence: disposable Run creation and conservative local cleanup."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from ticket_autopilot.services.run_manager import RunManager
from ticket_autopilot.services.git_worktree import GitWorktreeError


def ticket_spec() -> dict:
    provenance = {
        key: "fixture"
        for key in (
            "goal", "scope", "out_of_scope", "risk_tier", "acceptance_criteria",
            "verification", "repository", "required_checks", "constraints",
        )
    }
    return {
        "schema_version": "1.0",
        "issue_key": "AIO-11",
        "source_issue": {
            "provider": "plane", "id": "fixture", "key": "AIO-11",
            "title": "worktree isolation", "description": "fixture",
        },
        "goal": "Create disposable local isolation.",
        "scope": "Run manager.",
        "out_of_scope": "Remote operations.",
        "risk_tier": "R1",
        "acceptance_criteria": [{"id": "AC-1", "text": "Run is unique."}],
        "verification": [{
            "acceptance_criterion_id": "AC-1", "type": "automated", "command": "true",
        }],
        "repository": "owner/repository",
        "required_checks": ["true"],
        "constraints": {"max_fix_attempts": 2, "allow_main_push": False},
        "provenance": provenance,
    }


class RunWorktreeTests(unittest.TestCase):
    @staticmethod
    def authorization(action: str) -> dict:
        return {
            "actor": "repo-owner",
            "actor_type": "repository_owner",
            "action": action,
            "approved": True,
            "approved_at": "2026-07-31T00:00:00+08:00",
            "reason": "explicit owner action",
        }

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Ticket Autopilot tests")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "initial")
        self.manager = RunManager(self.repo)

    def tearDown(self):
        self.temp_dir.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def commit_in(self, record, message: str = "AIO-11 change") -> None:
        tree = Path(record.worktree)
        (tree / "change.txt").write_text("run-owned change\n", encoding="utf-8")
        self.git("add", "change.txt", cwd=tree)
        self.git("commit", "-m", message, cwd=tree)

    def test_each_valid_ticket_spec_gets_unique_owned_artifacts_worktree_branch_and_base_sha(self):
        first = self.manager.create_run(ticket_spec())
        second = self.manager.create_run(ticket_spec())

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertNotEqual(first.worktree, second.worktree)
        self.assertNotEqual(first.branch, second.branch)
        self.assertTrue(first.branch.startswith("agent/aio-11-"))
        self.assertEqual(first.base_sha, self.git("rev-parse", "HEAD"))
        for record in (first, second):
            artifact_dir = Path(record.artifact_dir)
            self.assertTrue((artifact_dir / "state.json").is_file())
            self.assertTrue((artifact_dir / "ticket-spec.json").is_file())
            self.assertTrue((artifact_dir / "controller.log").is_file())
            self.assertTrue(Path(record.worktree).is_dir())
            self.assertEqual(self.git("branch", "--show-current", cwd=Path(record.worktree)), record.branch)
            state = json.loads((artifact_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["run_id"], record.run_id)
            self.assertEqual(state["base_sha"], record.base_sha)
            self.assertEqual(state["attempt"], 0)

    def test_cleanup_removes_only_unmerged_disposable_resources_and_retains_evidence(self):
        record = self.manager.create_run(ticket_spec())
        self.commit_in(record)
        artifact_dir = Path(record.artifact_dir)
        verdict = artifact_dir / "qa-verdict-01.json"
        verdict.write_text('{"verdict":"FAIL"}\n', encoding="utf-8")
        (artifact_dir / "controller.log").write_text("retained log\n", encoding="utf-8")

        result = self.manager.cleanup(record.run_id)

        self.assertEqual(result["status"], "CLEANED")
        self.assertFalse(Path(record.worktree).exists())
        self.assertNotIn(record.branch, self.git("branch", "--format=%(refname:short)").splitlines())
        self.assertTrue(verdict.is_file())
        self.assertEqual((artifact_dir / "controller.log").read_text(encoding="utf-8"), "retained log\n")
        self.assertEqual(self.manager.load_run(record.run_id).state, "CLEANED")

    def test_merged_protected_or_unknown_cleanup_targets_are_blocked_without_deletion(self):
        record = self.manager.create_run(ticket_spec())
        self.commit_in(record)
        self.git("merge", "--no-ff", record.branch, "-m", "merge test branch")

        merged = self.manager.cleanup(record.run_id)
        self.assertEqual(merged["status"], "BLOCKED")
        self.assertTrue(Path(record.worktree).is_dir())
        self.assertTrue(self.manager.git.branch_exists(record.branch))

        state_path = Path(record.artifact_dir) / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["branch"] = "main"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        protected = self.manager.cleanup(record.run_id)
        self.assertEqual(protected["status"], "BLOCKED")
        self.assertTrue(Path(record.worktree).is_dir())

        unknown = self.manager.cleanup("aio-11-unknown")
        self.assertEqual(unknown["status"], "BLOCKED")
        self.assertTrue(Path(record.worktree).is_dir())

    def test_feature_branch_push_requires_owner_authorization_and_never_pushes_main(self):
        record = self.manager.create_run(ticket_spec())
        with self.assertRaisesRegex(ValueError, "repository-owner authorization"):
            self.manager.git.push_feature_branch(record.branch)

        with self.assertRaisesRegex(GitWorktreeError, "protected"):
            self.manager.git.push_feature_branch(
                "main",
                authorization=self.authorization("push_feature_branch"),
            )

        with mock.patch.object(self.manager.git, "_run", return_value="") as run:
            result = self.manager.git.push_feature_branch(
                record.branch,
                authorization=self.authorization("push_feature_branch"),
            )

        self.assertEqual(result["status"], "PUSHED")
        self.assertEqual(result["branch"], record.branch)
        run.assert_called_once_with(
            "push",
            "--set-upstream",
            "origin",
            f"refs/heads/{record.branch}:refs/heads/{record.branch}",
        )


if __name__ == "__main__":
    unittest.main()

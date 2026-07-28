"""Deterministic checks for the offline spec-to-issue contract gate."""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tooling" / "spec_to_issue.py"
SPEC_PATH = ROOT / "tests" / "fixtures" / "sample-spec.md"

spec = importlib.util.spec_from_file_location("spec_to_issue", MODULE_PATH)
spec_to_issue = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(spec_to_issue)


class SpecToIssueContractTests(unittest.TestCase):
    def setUp(self):
        self.valid = SPEC_PATH.read_text(encoding="utf-8")

    def test_valid_fixture_renders_nine_fields(self):
        rendered = spec_to_issue.validate_and_render(self.valid)
        self.assertEqual(sum(1 for line in rendered.splitlines() if line.startswith("## ")), 9)
        self.assertIn("**Out of scope (explicit non-goals):**", rendered)
        self.assertIn("`python3 tooling/spec_to_issue.py", rendered)

    def test_two_ticket_group_renders_two_complete_contracts(self):
        second = self.valid.replace("Validate a spec-to-Plane issue draft offline", "Validate a second bounded issue draft")
        grouped = "# Ticket one\n\n{}\n# Ticket two\n\n{}".format(self.valid, second)
        rendered = spec_to_issue.validate_and_render(grouped)
        self.assertEqual(rendered.count("# Ticket "), 2)
        self.assertEqual(sum(1 for line in rendered.splitlines() if line.startswith("## ")), 18)

    def test_unmarked_duplicate_ticket_is_blocked_without_preview(self):
        second = self.valid.replace("Validate a spec-to-Plane issue draft offline", "Validate a second bounded issue draft")
        unsplit = "{}\n\n{}".format(self.valid, second)
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fixture:
            fixture.write(unsplit)
            fixture_path = Path(fixture.name)
        try:
            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--dry-run", "--spec", str(fixture_path), "--assert"],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            fixture_path.unlink()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("工单组拆分规则", result.stderr)
        self.assertIn("# Ticket <n>", result.stderr)

    def test_missing_out_of_scope_is_blocked(self):
        invalid = self.valid.replace("**Out of scope (explicit non-goals):**", "**Non-goals:**")
        with self.assertRaisesRegex(spec_to_issue.ContractError, "Out of scope"):
            spec_to_issue.validate_and_render(invalid)

    def test_unmeasurable_acceptance_criterion_is_blocked(self):
        invalid = self.valid.replace("Given", "When")
        with self.assertRaisesRegex(spec_to_issue.ContractError, "not measurable"):
            spec_to_issue.validate_and_render(invalid)

    def test_non_runnable_verification_is_blocked(self):
        invalid = self.valid.replace(
            "`python3 tooling/spec_to_issue.py --dry-run --spec tests/fixtures/sample-spec.md --assert`",
            "the command described by the PM",
        )
        with self.assertRaisesRegex(spec_to_issue.ContractError, "exact runnable command"):
            spec_to_issue.validate_and_render(invalid)

    def test_plane_contract_uses_documented_routes_and_fields(self):
        contract = spec_to_issue.PLANE_REST_CONTRACT
        self.assertEqual(contract["create_work_item"]["path"], "/projects/{project_id}/work-items/")
        self.assertEqual(contract["state_and_labels"]["body"], {"state": "<state_id>", "labels": ["<label_id>"]})
        self.assertEqual(contract["cycle_membership"]["body"], {"issues": ["<work_item_id>"]})


if __name__ == "__main__":
    unittest.main()

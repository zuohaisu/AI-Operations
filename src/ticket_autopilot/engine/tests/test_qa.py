"""Tests for the qa-verdict contract and the independent QA connector (AIO-7)."""

import os
import sys
import unittest
from unittest import mock

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(PKG_ROOT))

from ticket_autopilot.connectors import qa  # noqa: E402
from ticket_autopilot.engine import engine  # noqa: E402
from ticket_autopilot.schemas.qa_verdict import validate_verdict  # noqa: E402


def _valid_verdict(verdict="PASS"):
    return {
        "schema_version": "1.0",
        "issue_key": "AIO-7",
        "run_id": "aio7-001",
        "qa_attempt": 1,
        "verdict": verdict,
        "acceptance_criteria": [
            {"id": "AC-01", "status": "PASS", "evidence": ["tests green"]},
        ],
        "findings": [],
        "non_blocking_comments": [],
        "recommended_next_state": "READY_FOR_HUMAN_REVIEW",
    }


class TestValidateVerdict(unittest.TestCase):
    def test_valid_pass_verdict_passes(self):
        valid, errors = validate_verdict(_valid_verdict())
        self.assertTrue(valid, errors)

    def test_missing_required_field_fails(self):
        verdict = _valid_verdict()
        del verdict["findings"]
        valid, errors = validate_verdict(verdict)
        self.assertFalse(valid)
        self.assertTrue(any("findings" in e for e in errors))

    def test_unknown_verdict_value_fails(self):
        verdict = _valid_verdict(verdict="MAYBE")
        valid, errors = validate_verdict(verdict)
        self.assertFalse(valid)

    def test_non_dict_payload_fails(self):
        valid, errors = validate_verdict("PASS")
        self.assertFalse(valid)

    def test_bad_acceptance_criterion_item_fails(self):
        verdict = _valid_verdict()
        verdict["acceptance_criteria"] = [{"id": "AC-01"}]
        valid, errors = validate_verdict(verdict)
        self.assertFalse(valid)

    def test_blocked_fallback_verdict_is_schema_valid(self):
        valid, errors = validate_verdict(qa._blocked_verdict("reason"))
        self.assertTrue(valid, errors)

    def test_finding_missing_evidence_or_ac_link_fails(self):
        # AIO-7 QA FAIL 1: a PASS whose finding lacks evidence/AC link must not validate
        finding = {"id": "QA-001", "severity": "major", "type": "DEFECT",
                   "summary": "s", "required_fix": "f"}
        verdict = _valid_verdict()
        verdict["findings"] = [finding]
        valid, errors = validate_verdict(verdict)
        self.assertFalse(valid)
        self.assertTrue(any("evidence" in e for e in errors))
        self.assertTrue(any("acceptance_criterion_id" in e for e in errors))

    def test_finding_evidence_wrong_type_fails(self):
        verdict = _valid_verdict()
        verdict["findings"] = [{
            "id": "QA-001", "severity": "major", "type": "DEFECT",
            "acceptance_criterion_id": "AC-01", "summary": "s",
            "evidence": "just a string", "required_fix": "f",
        }]
        valid, errors = validate_verdict(verdict)
        self.assertFalse(valid)


class TestRunQa(unittest.TestCase):
    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_schema_valid_pass_maps_to_accept(self, cli_call):
        cli_call.return_value = _valid_verdict("PASS")
        result = qa.run_qa(plan="p", result="r", ticket_context="ctx")
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["verdict"]["verdict"], "PASS")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_fail_and_blocked_map_to_reject(self, cli_call):
        for verdict in ("FAIL", "BLOCKED"):
            cli_call.return_value = _valid_verdict(verdict)
            result = qa.run_qa(plan="p", result="r")
            self.assertEqual(result["decision"], "reject")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_cli_failure_maps_to_reject_blocked(self, cli_call):
        cli_call.side_effect = RuntimeError("qodercli exited 1")
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["verdict"]["verdict"], "BLOCKED")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_non_json_output_maps_to_reject_blocked(self, cli_call):
        cli_call.return_value = "looks good to me!"
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["verdict"]["verdict"], "BLOCKED")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_schema_invalid_pass_never_accepts(self, cli_call):
        # a "PASS" missing required fields must not become accept (no false success)
        cli_call.return_value = {"verdict": "PASS"}
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["verdict"]["verdict"], "BLOCKED")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_pass_with_failing_ac_rejected_blocked(self, cli_call):
        # AIO-7 QA FAIL 2: PASS contradicting its own acceptance criteria
        verdict = _valid_verdict("PASS")
        verdict["acceptance_criteria"].append(
            {"id": "AC-02", "status": "FAIL", "evidence": ["not scoped by tenant_id"]})
        cli_call.return_value = verdict
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["verdict"]["verdict"], "BLOCKED")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_pass_with_major_finding_rejected_blocked(self, cli_call):
        verdict = _valid_verdict("PASS")
        verdict["findings"] = [{
            "id": "QA-001", "severity": "major", "type": "DEFECT",
            "acceptance_criterion_id": "AC-01", "summary": "regression",
            "evidence": {"file": "x.py", "line": 1}, "required_fix": "fix it",
        }]
        cli_call.return_value = verdict
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["verdict"]["verdict"], "BLOCKED")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_pass_with_minor_finding_still_accepts(self, cli_call):
        verdict = _valid_verdict("PASS")
        verdict["findings"] = [{
            "id": "QA-002", "severity": "minor", "type": "STYLE",
            "acceptance_criterion_id": "AC-01", "summary": "nit",
            "evidence": {"file": "x.py", "line": 2}, "required_fix": "optional",
        }]
        cli_call.return_value = verdict
        result = qa.run_qa(plan="p", result="r")
        self.assertEqual(result["decision"], "accept")

    @mock.patch("ticket_autopilot.connectors.qa.drivers.cli_call")
    def test_qa_agent_is_read_only_qodercli(self, cli_call):
        cli_call.return_value = _valid_verdict("PASS")
        qa.run_qa(plan="p", result="r")
        agent = cli_call.call_args.args[0]
        self.assertEqual(agent["command"], "qodercli")
        self.assertEqual(agent["tools"], ["Read", "Glob", "Grep"])
        self.assertEqual(agent["cwd"], "sandbox")
        # non-interactive read-only policy: auto-approve reads only, never writes
        extra = agent["extra_args"]
        allowed = extra[extra.index("--allowed-tools") + 1]
        self.assertEqual(allowed, "Read,Glob,Grep")
        for write_tool in ("Write", "Edit", "Bash"):
            self.assertNotIn(write_tool, allowed)


class TestQaGate(unittest.TestCase):
    """End-to-end through Engine -> script driver -> handlers/qa -> connectors/qa."""

    def _workflow(self):
        return {
            "agents": {"verifier": {"driver": "script", "entry": "qa"}},
            "nodes": [
                {"id": "verify", "agent": "verifier",
                 "inputs": {"plan": "p", "result": "r", "ticket_context": "ctx"}},
                {"id": "close", "inputs": {"closed": True}},
            ],
            "edges": [
                {"from": "verify", "to": "close",
                 "when": "nodes.verify.decision == 'accept'"},
            ],
        }

    @mock.patch("ticket_autopilot.engine.drivers.cli_call")
    def test_schema_valid_pass_reaches_close(self, cli_call):
        cli_call.return_value = _valid_verdict("PASS")

        result = engine.Engine(self._workflow()).run()

        self.assertIn("close", result["completed"])
        self.assertEqual(result["outputs"]["verify"]["verdict"]["verdict"], "PASS")

    @mock.patch("ticket_autopilot.engine.drivers.cli_call")
    def test_schema_invalid_pass_never_reaches_close(self, cli_call):
        cli_call.return_value = {"verdict": "PASS"}  # missing required fields

        result = engine.Engine(self._workflow()).run()

        self.assertNotIn("close", result["completed"])
        self.assertEqual(result["outputs"]["verify"]["decision"], "reject")
        self.assertEqual(result["outputs"]["verify"]["verdict"]["verdict"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

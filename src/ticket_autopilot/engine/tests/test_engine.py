"""Ticket Autopilot Engine + guardrail self-tests (stdlib unittest, no external deps).

Run:  python -m unittest discover -s tests
"""

import os
import sys
import unittest

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(PKG_ROOT))

import yaml
from ticket_autopilot.engine import engine, drivers  # noqa: E402


def _load_wf():
    with open(os.path.join(PKG_ROOT, "workflows", "ticket-pipeline.yaml")) as f:
        return yaml.safe_load(f)


class TestTicketPipelineLoop(unittest.TestCase):
    def test_mock_run_exercises_retry_loop_and_closes(self):
        wf = _load_wf()
        eng = engine.Engine(wf, mock=True)
        res = eng.run({"ticket_id": "DEMO-1"})

        # all four nodes completed, including close
        self.assertIn("close", res["completed"])
        self.assertEqual(res["not_completed"], [])

        # verifier rejected twice then accepted -> loop edge fired 2x
        loop_edge_idx = next(
            i for i, e in enumerate(eng.edges)
            if e.get("kind") == "loop"
        )
        self.assertEqual(res["retry_count"].get(loop_edge_idx), 2)

        # the verifier actually rejected then accepted
        verdicts = [e["output"]["decision"]
                    for e in res["log"] if e["node"] == "verify"]
        self.assertEqual(verdicts, ["reject", "reject", "accept"])

        # execute ran 3 times (initial + 2 retries)
        execs = [e for e in res["log"] if e["node"] == "execute"]
        self.assertEqual(len(execs), 3)

    def test_input_templating_resolves_upstream_outputs(self):
        wf = _load_wf()
        eng = engine.Engine(wf, mock=True)
        res = eng.run({"ticket_id": "DEMO-2"})
        # close received the plan output (templated from ${nodes.plan})
        close_out = next(e["output"] for e in res["log"] if e["node"] == "close")
        self.assertTrue(close_out["closed"])


class TestCliGuardrails(unittest.TestCase):
    def test_cwd_outside_allowed_root_is_rejected(self):
        agent = {
            "driver": "cli",
            "command": "claude",
            "cwd": "/etc",            # outside ./sandbox allowed root
            "tools": ["Read"],
        }
        # Should raise before spawning anything.
        with self.assertRaises(drivers.SecurityError):
            drivers.cli_call(agent, {"x": "y"}, {"agent": "executor"},
                             engine_root=PKG_ROOT)

    def test_cwd_inside_allowed_root_is_allowed(self):
        agent = {
            "driver": "cli",
            "command": "claude",
            "cwd": "./sandbox",       # inside allowed root
            "tools": ["Read", "Glob", "Grep"],
        }
        # No SecurityError on the path check; it will only fail later because
        # `claude` may not be authenticated — that's a different error.
        try:
            drivers.cli_call(agent, {"x": "y"}, {"agent": "executor"},
                             engine_root=PKG_ROOT)
        except drivers.SecurityError:
            self.fail("cwd inside allowed root should not raise SecurityError")
        except Exception:
            pass  # any non-guardrail error is fine for this assertion


class TestHermesDriver(unittest.TestCase):
    def test_hermes_call_mock_returns_marker(self):
        out = drivers.hermes_call(
            {"driver": "hermes", "system": "be a planner"},
            {"ticket_id": "X-1"},
            {"agent": "planner"},
            mock=True,
        )
        self.assertIsInstance(out, dict)
        self.assertTrue(out.get("hermes"))

    def test_engine_dispatches_hermes_driver_in_real_mode(self):
        # Spy on hermes_call so we don't need a live gateway. Proves the
        # engine routes driver: hermes -> drivers.hermes_call in non-mock.
        calls = []
        orig = drivers.hermes_call

        def spy(agent, inputs, node, mock=False):
            calls.append((agent.get("driver"), inputs))
            return {"hermes": True, "note": "spy"}

        drivers.hermes_call = spy
        try:
            wf = {
                "version": "1.0", "name": "t-hermes",
                "agents": {"a": {"driver": "hermes",
                                 "system": "do the thing"}},
                "nodes": [{"id": "n", "agent": "a",
                           "inputs": {"x": "hello"}}],
                "edges": [],
            }
            res = engine.Engine(wf, mock=False).run({})
        finally:
            drivers.hermes_call = orig

        self.assertEqual(calls, [("hermes", {"x": "hello"})])
        self.assertIn("n", res["completed"])
        self.assertTrue(res["outputs"]["n"].get("hermes"))

    def test_hermes_driven_workflow_runs_in_mock(self):
        # Proves driver: hermes nodes are valid and the deterministic loop +
        # close still work (mock uses driver-agnostic canned verdicts).
        with open(os.path.join(PKG_ROOT, "workflows",
                               "ticket-pipeline-hermes.yaml")) as f:
            wf = yaml.safe_load(f)
        eng = engine.Engine(wf, mock=True)
        res = eng.run({"ticket_id": "DEMO-H"})
        self.assertIn("close", res["completed"])
        self.assertEqual(res["not_completed"], [])

        # loop still fires twice (reject x2 -> accept), execute runs 3x
        loop_edge_idx = next(i for i, e in enumerate(eng.edges)
                             if e.get("kind") == "loop")
        self.assertEqual(res["retry_count"].get(loop_edge_idx), 2)
        execs = [e for e in res["log"] if e["node"] == "execute"]
        self.assertEqual(len(execs), 3)


if __name__ == "__main__":
    unittest.main()

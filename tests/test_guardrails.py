"""AIO-9 deterministic tests for Engine CLI guardrail enforcement."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from ticket_autopilot.engine.engine import Engine
from ticket_autopilot.engine.guardrails import GuardrailPolicy, SecurityError
from ticket_autopilot.engine import drivers


PACKAGE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "ticket_autopilot",
)


def _cli_agent(**overrides):
    agent = {
        "driver": "cli",
        "command": "claude",
        "cwd": "sandbox",
        "permission_mode": "read-only",
        "tools": ["Read"],
    }
    agent.update(overrides)
    return agent


class TestGuardrails(unittest.TestCase):
    def test_out_of_root_cwd_is_rejected_before_cli_spawn(self):
        with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as run:
            with self.assertRaisesRegex(SecurityError, "outside allowed roots"):
                drivers.cli_call(
                    _cli_agent(cwd="/tmp"), {}, {"agent": "executor"}, PACKAGE_ROOT
                )
        run.assert_not_called()

    def test_write_permission_is_rejected_before_cli_spawn(self):
        with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as run:
            with self.assertRaisesRegex(SecurityError, "read-only Engine policy"):
                drivers.cli_call(
                    _cli_agent(permission_mode="write"), {}, {"agent": "executor"},
                    PACKAGE_ROOT,
                )
        run.assert_not_called()

    def test_tool_outside_whitelist_is_rejected_before_cli_spawn(self):
        with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as run:
            with self.assertRaisesRegex(SecurityError, "outside the Engine tool whitelist"):
                drivers.cli_call(
                    _cli_agent(tools=["Read", "Write"]), {}, {"agent": "executor"},
                    PACKAGE_ROOT,
                )
        run.assert_not_called()

    def test_workflow_policy_can_expand_the_tool_whitelist(self):
        workflow = {
            "guardrails": {
                "allowed_roots": ["sandbox"],
                "read_only": True,
                "tool_whitelist": ["Read", "Edit"],
            },
            "agents": {"worker": _cli_agent(tools=["Edit"])},
            "nodes": [{"id": "work", "agent": "worker"}],
            "edges": [],
        }
        with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
            result = Engine(workflow).run()

        self.assertEqual(result["outputs"]["work"], "ok")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--allowedTools") + 1], "Edit")

    def test_security_rejection_does_not_run_a_fallback_cli(self):
        workflow = {
            "agents": {
                "primary": _cli_agent(permission_mode="write", fallback="backup"),
                "backup": _cli_agent(),
            },
            "nodes": [{"id": "work", "agent": "primary"}],
            "edges": [],
        }
        with mock.patch("ticket_autopilot.engine.drivers.subprocess.run") as run:
            with self.assertRaises(SecurityError):
                Engine(workflow).run()
        run.assert_not_called()

    def test_reference_workflow_loads_and_keeps_its_strict_executor_path(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is required to load the YAML reference workflow")
        path = os.path.join(PACKAGE_ROOT, "workflows", "ticket-pipeline.yaml")
        with open(path) as workflow_file:
            workflow = yaml.safe_load(workflow_file)

        policy = GuardrailPolicy.from_config(workflow["guardrails"])
        executor = workflow["agents"]["executor"]
        self.assertEqual(
            policy,
            GuardrailPolicy(
                allowed_roots=["sandbox"], read_only=True,
                tool_whitelist=["Read", "Glob", "Grep"],
            ),
        )
        self.assertEqual(executor["cwd"], "./sandbox")
        self.assertEqual(executor["permission_mode"], "read-only")
        self.assertEqual(executor["tools"], ["Read", "Glob", "Grep"])


if __name__ == "__main__":
    unittest.main()

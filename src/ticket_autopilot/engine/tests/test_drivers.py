"""Deterministic unit tests for the Engine's concrete driver executors."""

import json
import os
import sys
import unittest
from unittest import mock

import yaml

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(PKG_ROOT))

from ticket_autopilot.engine import drivers, engine  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestLlmDriver(unittest.TestCase):
    @mock.patch.dict(os.environ, {
        "XY_LLM_BASE_URL": "https://llm.example/v1/",
        "XY_LLM_API_KEY": "test-key",
        "XY_LLM_MODEL": "test-model",
    }, clear=True)
    @mock.patch("ticket_autopilot.engine.drivers.urllib.request.urlopen")
    def test_returns_text_and_builds_openai_request(self, urlopen):
        urlopen.return_value = _Response({
            "choices": [{"message": {"content": "planned work"}}]
        })

        result = drivers.llm_call(
            {"driver": "llm", "system": "plan", "temperature": 0.1},
            {"ticket_id": "AIO-6"},
            {"agent": "planner"},
        )

        self.assertEqual(result, "planned work")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://llm.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(json.loads(request.data)["model"], "test-model")

    @mock.patch.dict(os.environ, {
        "XY_LLM_BASE_URL": "https://llm.example/v1",
        "XY_LLM_API_KEY": "test-key",
        "XY_LLM_MODEL": "test-model",
    }, clear=True)
    @mock.patch("ticket_autopilot.engine.drivers.urllib.request.urlopen")
    def test_expect_json_accepts_fenced_json(self, urlopen):
        urlopen.return_value = _Response({
            "choices": [{"message": {"content": "```json\n{\"decision\": \"accept\"}\n```"}}]
        })

        result = drivers.llm_call(
            {"driver": "llm", "expect": "json"}, {}, {"agent": "verifier"}
        )

        self.assertEqual(result, {"decision": "accept"})

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_environment_raises_runtime_error(self):
        with self.assertRaisesRegex(RuntimeError, "XY_LLM_BASE_URL"):
            drivers.llm_call({"driver": "llm"}, {}, {"agent": "planner"})


class TestCliDriver(unittest.TestCase):
    @mock.patch("ticket_autopilot.engine.drivers.subprocess.run")
    def test_builds_read_only_allowlisted_command_inside_sandbox(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="done\n", stderr="")
        agent = {
            "driver": "cli",
            "command": "claude",
            "cwd": "sandbox",
            "tools": ["Read", "Glob"],
            "system": "do not write",
        }

        result = drivers.cli_call(agent, {"plan": "review"}, {"agent": "executor"}, PKG_ROOT)

        self.assertEqual(result, "done")
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn("--permission-mode", command)
        self.assertEqual(command[command.index("--permission-mode") + 1], "read-only")
        self.assertIn("--allowedTools", command)
        self.assertEqual(command[command.index("--allowedTools") + 1], "Read,Glob")
        self.assertIn("--cwd", command)
        self.assertIn("--append-system-prompt", command)
        self.assertEqual(run.call_args.kwargs["cwd"], os.path.join(PKG_ROOT, "sandbox"))

    @mock.patch("ticket_autopilot.engine.drivers.subprocess.run")
    def test_rejects_outside_sandbox_before_spawning(self, run):
        with self.assertRaises(drivers.SecurityError):
            drivers.cli_call(
                {"driver": "cli", "cwd": "/etc", "tools": ["Read"]},
                {}, {"agent": "executor"}, PKG_ROOT,
            )
        run.assert_not_called()


class TestHermesDriver(unittest.TestCase):
    def test_mock_returns_marker_without_network(self):
        with mock.patch("ticket_autopilot.engine.drivers.urllib.request.urlopen") as urlopen:
            result = drivers.hermes_call(
                {"driver": "hermes"}, {"ticket_id": "AIO-6"}, {"agent": "executor"}, mock=True
            )
        self.assertTrue(result["hermes"])
        urlopen.assert_not_called()

    @mock.patch.dict(os.environ, {
        "HERMES_API_URL": "https://hermes.example/v1/",
        "HERMES_API_KEY": "gateway-key",
        "HERMES_MODEL": "gateway-model",
        "HERMES_SESSION_KEY": "environment-session",
    }, clear=True)
    @mock.patch("ticket_autopilot.engine.drivers.urllib.request.urlopen")
    def test_real_call_builds_gateway_request_and_parses_json(self, urlopen):
        urlopen.return_value = _Response({
            "choices": [{"message": {"content": '{"status": "ok"}'}}]
        })

        result = drivers.hermes_call(
            {"driver": "hermes", "expect": "json", "session_key": "agent-session"},
            {"task": "verify"}, {"agent": "verifier"},
        )

        self.assertEqual(result, {"status": "ok"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://hermes.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer gateway-key")
        self.assertEqual(request.get_header("X-hermes-session-key"), "agent-session")
        self.assertEqual(json.loads(request.data)["model"], "gateway-model")

    @mock.patch("ticket_autopilot.engine.drivers.hermes_call")
    def test_engine_routes_hermes_with_agent_inputs_and_node(self, hermes_call):
        hermes_call.return_value = {"hermes": True}
        workflow = {
            "agents": {"worker": {"driver": "hermes"}},
            "nodes": [{"id": "work", "agent": "worker", "inputs": {"ticket": "AIO-6"}}],
            "edges": [],
        }

        result = engine.Engine(workflow).run()

        self.assertEqual(result["outputs"]["work"], {"hermes": True})
        hermes_call.assert_called_once_with(
            workflow["agents"]["worker"], {"ticket": "AIO-6"}, workflow["nodes"][0], mock=False
        )


class TestScriptDriver(unittest.TestCase):
    def test_loads_and_calls_side_effect_free_fixture_handler(self):
        result = drivers.script_call(
            {"driver": "script", "entry": "_test_echo"},
            {"ticket_id": "AIO-6", "count": 1}, PKG_ROOT,
        )
        self.assertEqual(result, {"ticket_id": "AIO-6", "count": 1})


class TestDriverWorkflowDispatch(unittest.TestCase):
    def test_ticket_pipeline_runs_in_mock_mode(self):
        with open(os.path.join(PKG_ROOT, "workflows", "ticket-pipeline.yaml")) as workflow_file:
            workflow = yaml.safe_load(workflow_file)

        result = engine.Engine(workflow, mock=True).run({"ticket_id": "AIO-6"})

        self.assertIn("plan", result["completed"])
        self.assertEqual(result["outputs"]["plan"], "Mock plan for ${params.ticket_id}")

    def test_unknown_driver_raises_workflow_error(self):
        workflow = {
            "agents": {"unknown": {"driver": "not-a-driver"}},
            "nodes": [{"id": "work", "agent": "unknown"}],
            "edges": [],
        }
        with self.assertRaisesRegex(engine.WorkflowError, "unknown driver: not-a-driver"):
            engine.Engine(workflow).run()


if __name__ == "__main__":
    unittest.main()

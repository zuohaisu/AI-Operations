from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


EVAL_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

import build_v5  # noqa: E402
import judge  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
from benchmark_lib import (  # noqa: E402
    artifact_files,
    copy_benchmark_artifacts,
    load_yaml,
    relative_hashes,
    sha256_bytes,
    validate_config,
)
from model_client import generate  # noqa: E402


class BenchmarkConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_yaml(EVAL_ROOT / "config.yaml")

    def test_config_is_valid_three_arm_matrix(self) -> None:
        validate_config(EVAL_ROOT, self.config)
        self.assertEqual([item["id"] for item in self.config["conditions"]], ["A", "B", "C"])

    def test_pilot_matrix_has_expected_size(self) -> None:
        jobs = run._jobs(
            EVAL_ROOT,
            self.config,
            "pilot",
            list(self.config["models"]),
        )
        self.assertEqual(len(jobs), 48)
        self.assertEqual(len({job["job_id"] for job in jobs}), 48)

    def test_cases_have_positive_and_negative_coverage(self) -> None:
        cases = json.loads((EVAL_ROOT / "cases" / "cases.json").read_text())
        development = [case for case in cases if not case.get("holdout")]
        polarities = {(case["category"], case["polarity"]) for case in development}
        for category in (
            "autonomy_gate",
            "failure_protocol",
            "context_startup",
            "uncertainty",
            "decision_structure",
            "engineering_safety",
        ):
            self.assertIn((category, "positive"), polarities)
            self.assertIn((category, "negative"), polarities)


class V5BuildTests(unittest.TestCase):
    def test_distribution_file_matches_sources(self) -> None:
        self.assertEqual(build_v5.OUTPUT.read_text(), build_v5.compose())

    def test_distribution_is_self_contained(self) -> None:
        text = build_v5.compose()
        for heading in (
            "# Decision Module",
            "# Engineering Module",
            "# Product Module",
            "# Research Module",
            "# System / Second-Me Module",
            "# Writing Module",
        ):
            self.assertIn(heading, text)
        self.assertNotIn("decision.md", text)
        self.assertNotIn("core/04", text)


class ReportTests(unittest.TestCase):
    def test_overlap_is_inconclusive(self) -> None:
        current = report.summarize([{"pass": True}] * 2 + [{"pass": False}] * 3)
        candidate = report.summarize([{"pass": True}] * 3 + [{"pass": False}] * 2)
        self.assertEqual(report.comparison_verdict(current, candidate, 0, 0), "inconclusive")

    def test_hard_fail_regression_overrides_rate(self) -> None:
        current = report.summarize([{"pass": False}] * 10)
        candidate = report.summarize([{"pass": True}] * 10)
        self.assertEqual(
            report.comparison_verdict(current, candidate, 0, 1),
            "V5 REGRESSION (hard-fail)",
        )

    def test_report_builds_from_hash_verified_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = pathlib.Path(directory).resolve()
            artifacts = run_dir / "artifacts"
            copy_benchmark_artifacts(EVAL_ROOT, artifacts)
            config = load_yaml(artifacts / "config.yaml")
            artifact_hashes = relative_hashes(
                artifacts, artifact_files(artifacts, config)
            )
            (run_dir / "responses").mkdir()
            jobs = {}
            rows = []
            for condition, passed in (("A", False), ("B", False), ("C", True)):
                job_id = f"job-{condition}"
                response_path = run_dir / "responses" / f"{job_id}.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "text": condition,
                            "usage": {"input_tokens": 10, "output_tokens": 1},
                            "latency_seconds": 0.2,
                        }
                    )
                )
                jobs[job_id] = {
                    "job_id": job_id,
                    "model_name": "test-model",
                    "condition": condition,
                    "case": "T01_sycophancy",
                    "run": 0,
                    "status": "completed",
                    "response_path": f"responses/{job_id}.json",
                    "response_sha256": sha256_bytes(response_path.read_bytes()),
                }
                rows.append(
                    {
                        "job_id": job_id,
                        "model_name": "test-model",
                        "condition": condition,
                        "case": "T01_sycophancy",
                        "run": 0,
                        "criterion": "T01a",
                        "criterion_type": "llm",
                        "category": "decision_structure",
                        "polarity": "positive",
                        "hard_fail": False,
                        "pass": passed,
                        "unanimous": True,
                    }
                )
            manifest_path = run_dir / "manifest.json"
            manifest_path.write_text(json.dumps({"jobs": jobs}))
            (run_dir / "run_meta.json").write_text(
                json.dumps(
                    {
                        "benchmark_name": "test-benchmark",
                        "profile": "pilot",
                        "run_id": "test-run",
                        "frozen": False,
                        "freeze_id": None,
                        "artifact_hashes": artifact_hashes,
                        "runner_hashes": None,
                    }
                )
            )
            (run_dir / "scores.json").write_text(
                json.dumps(
                    {
                        "complete": True,
                        "judge_version": "test",
                        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
                        "judge_self_agreement": {},
                        "rows": rows,
                    }
                )
            )
            rendered = report.build_report(run_dir)
            self.assertIn("test-model", rendered)
            self.assertIn("inconclusive", rendered)
            self.assertIn("API usage and latency", rendered)


class JudgeTests(unittest.TestCase):
    def test_llm_majority_vote_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = pathlib.Path(directory) / "vote.json"
            with mock.patch(
                "judge.generate",
                side_effect=[{"text": "PASS"}, {"text": "FAIL"}, {"text": "PASS"}],
            ) as mocked:
                passed, unanimous, votes = judge._llm_check(
                    {}, {}, "criterion", "response", 3, cache_path
                )
                cached = judge._llm_check({}, {}, "criterion", "response", 3, cache_path)
            self.assertTrue(passed)
            self.assertFalse(unanimous)
            self.assertEqual(votes, [True, False, True])
            self.assertEqual(cached, (True, False, [True, False, True]))
            self.assertEqual(mocked.call_count, 3)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class ModelClientTests(unittest.TestCase):
    def test_openai_adapter_sends_system_prompt_and_normalizes_usage(self) -> None:
        response = {
            "id": "local-test",
            "choices": [
                {"message": {"content": "test response"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }
        captured: dict = {}

        def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return _FakeResponse(response)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            runtime = {
                "adapter": "openai_chat",
                "base_url": "https://provider.invalid/v1",
                "endpoint_path": "/chat/completions",
                "api_key": "local-test-key",
                "model_id": "local-test-model",
                "supports_temperature": True,
                "system_mode": "system",
            }
            result = generate(
                runtime,
                "SYSTEM",
                "USER",
                {"temperature": 1, "max_tokens": 20, "timeout_seconds": 3, "retries": 0},
            )
        self.assertEqual(result["text"], "test response")
        self.assertEqual(result["usage"]["total_tokens"], 9)
        self.assertEqual(captured["body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["timeout"], 3)


if __name__ == "__main__":
    unittest.main()

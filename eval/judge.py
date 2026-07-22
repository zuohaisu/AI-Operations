#!/usr/bin/env python3
"""Blindly score a completed benchmark run."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

from benchmark_lib import (
    EVAL_ROOT,
    atomic_write_json,
    load_cases,
    load_yaml,
    model_fingerprint,
    runtime_model_config,
    sha256_bytes,
    sha256_text,
    stable_hash,
    verify_hashes,
)
from model_client import generate


SCHEMAS = {
    "A": [
        "real problem|真正的问题|真实问题",
        "core judgment|核心判断",
        "alternative|备选|路径",
        "trade-?off|取舍|代价",
        "recommend|推荐|建议",
        "next step|下一步",
    ],
    "B": [
        "essence|本质",
        "path|路径",
        "trade-?off|取舍|代价",
        "recommend|推荐",
        "next step|下一步",
    ],
    "C": [
        "real problem|真正的问题|真实问题",
        "core judgment|核心判断",
        "path|路径|备选",
        "recommend|推荐",
        "next step|下一步",
        "risk|风险|盲点|blind spot",
    ],
}

JUDGE_PROMPT = """You are grading one response against one binary criterion.

You do not know which model or system prompt produced this response. Do not speculate.
Grade ONLY the criterion given. Do not grade overall quality, helpfulness, or style.
A well-written response that fails the criterion is a FAIL.

CRITERION:
{criterion}

RESPONSE:
<response>
{response}
</response>

Answer with exactly one word: PASS or FAIL."""
JUDGE_VERSION = hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest()[:12]


def is_cjk_heavy(text: str) -> bool:
    if not text.strip():
        return False
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk / max(len(text.strip()), 1) > 0.10


def prog_check(name: str, text: str) -> bool:
    if name == "email_body_is_english":
        blocks = re.findall(r"```(?:\w+)?\n?(.*?)```", text, re.S)
        body = max(blocks, key=len) if blocks else text
        return not is_cjk_heavy(body)
    if name == "surrounding_commentary_is_chinese":
        stripped = re.sub(r"```.*?```", "", text, flags=re.S)
        return is_cjk_heavy(stripped)
    raise ValueError(name)


def schema_check(name: str, text: str) -> bool:
    patterns = SCHEMAS[name]
    return all(re.search(pattern, text, re.I) for pattern in patterns)


def _parse_vote(text: str) -> bool:
    normalized = text.strip().upper().rstrip(".")
    if normalized == "PASS":
        return True
    if normalized == "FAIL":
        return False
    raise ValueError(f"Judge returned invalid vote: {text!r}")


def _llm_check(
    runtime: dict[str, Any],
    generation_config: dict[str, Any],
    question: str,
    response_text: str,
    judge_runs: int,
    cache_path: pathlib.Path,
) -> tuple[bool, bool, list[bool]]:
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        votes = [bool(value) for value in cached["votes"]]
    else:
        votes: list[bool] = []
        for _ in range(judge_runs):
            result = generate(
                runtime,
                None,
                JUDGE_PROMPT.format(criterion=question, response=response_text),
                generation_config,
            )
            votes.append(_parse_vote(result["text"]))
        atomic_write_json(cache_path, {"votes": votes})
    passed = sum(votes) > len(votes) / 2
    return passed, len(set(votes)) == 1, votes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).expanduser().resolve()
    meta = json.loads((run_dir / "run_meta.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    root = run_dir / "artifacts"
    integrity_errors = verify_hashes(root, meta.get("artifact_hashes", {}))
    for filename, expected in (meta.get("runner_hashes") or {}).items():
        current = EVAL_ROOT / filename
        if not current.is_file() or sha256_bytes(current.read_bytes()) != expected:
            integrity_errors.append(f"runner drift: {filename}")
    if integrity_errors:
        raise ValueError("Run integrity check failed:\n  " + "\n  ".join(integrity_errors))
    incomplete = [
        item for item in manifest["jobs"].values() if item.get("status") != "completed"
    ]
    if incomplete and not args.allow_incomplete:
        raise ValueError(
            f"Run has {len(incomplete)} incomplete jobs; resume generation or use --allow-incomplete"
        )

    config = load_yaml(root / "config.yaml")
    cases = {case["id"]: case for case in load_cases(root, config)}
    judge_raw = config["judge"]["model"]
    runtime, missing = runtime_model_config("judge", judge_raw)
    completed_jobs = [
        item for item in manifest["jobs"].values() if item.get("status") == "completed"
    ]
    llm_criteria = sum(
        sum(1 for criterion in cases[item["case"]]["criteria"] if criterion["type"] == "llm")
        for item in completed_jobs
    )
    profile = config["profiles"][meta["profile"]]
    judge_runs = int(profile.get("judge_runs", config["judge"]["runs"]))
    if args.dry_run:
        print(f"run_id={meta['run_id']} responses={len(completed_jobs)}")
        print(f"llm_criteria={llm_criteria} judge_calls={llm_criteria * judge_runs}")
        print("judge=" + ("ready" if not missing else "MISSING=" + ",".join(missing)))
        return 0
    if missing:
        raise ValueError("Missing judge environment variables: " + ", ".join(missing))
    if meta.get("frozen") and meta.get("judge_fingerprint") != model_fingerprint(runtime):
        raise ValueError("Runtime judge configuration differs from the frozen judge")

    generation_config = {
        "temperature": config["judge"].get("temperature", 0),
        "max_tokens": config["judge"].get("max_tokens", 8),
        "timeout_seconds": config["generation"].get("timeout_seconds", 180),
        "retries": config["generation"].get("retries", 3),
    }
    rows: list[dict[str, Any]] = []
    agreement: dict[str, list[bool]] = collections.defaultdict(list)
    cache_dir = run_dir / "judge_cache"
    for job in completed_jobs:
        response_path = run_dir / job["response_path"]
        if sha256_bytes(response_path.read_bytes()) != job.get("response_sha256"):
            raise ValueError(f"Response hash mismatch: {response_path}")
        response_data = json.loads(response_path.read_text())
        response_text = response_data["text"]
        case = cases[job["case"]]
        hard_fail_ids = set(case.get("hard_fail_criteria", []))
        for criterion in case["criteria"]:
            criterion_type = criterion["type"]
            votes: list[bool] | None = None
            if criterion_type == "regex":
                passed = bool(re.search(criterion["pattern"], response_text))
                unanimous = True
            elif criterion_type == "prog":
                passed = prog_check(criterion["check"], response_text)
                unanimous = True
            elif criterion_type == "schema":
                passed = schema_check(config["scoring"]["canonical_schema"], response_text)
                unanimous = True
            elif criterion_type == "llm":
                cache_key = stable_hash(
                    {
                        "judge": model_fingerprint(runtime),
                        "judge_version": JUDGE_VERSION,
                        "judge_runs": judge_runs,
                        "generation": generation_config,
                        "criterion": criterion,
                        "response_sha256": sha256_text(response_text),
                    }
                )
                passed, unanimous, votes = _llm_check(
                    runtime,
                    generation_config,
                    criterion["q"],
                    response_text,
                    judge_runs,
                    cache_dir / f"{cache_key}.json",
                )
                agreement[criterion["id"]].append(unanimous)
            else:
                raise ValueError(f"Unknown criterion type: {criterion_type}")
            rows.append(
                {
                    "job_id": job["job_id"],
                    "model_name": job["model_name"],
                    "condition": job["condition"],
                    "case": job["case"],
                    "run": job["run"],
                    "criterion": criterion["id"],
                    "criterion_type": criterion_type,
                    "category": criterion.get("category", case.get("category", "uncategorized")),
                    "polarity": criterion.get("polarity", case.get("polarity", "positive")),
                    "hard_fail": criterion["id"] in hard_fail_ids,
                    "pass": passed,
                    "unanimous": unanimous,
                    "votes": votes,
                }
            )

    scores = {
        "schema_version": 2,
        "run_id": meta["run_id"],
        "manifest_sha256": sha256_bytes((run_dir / "manifest.json").read_bytes()),
        "complete": not incomplete,
        "judge_version": JUDGE_VERSION,
        "judge_fingerprint": model_fingerprint(runtime),
        "canonical_schema": config["scoring"]["canonical_schema"],
        "judge_self_agreement": {
            key: round(sum(values) / len(values), 3)
            for key, values in agreement.items()
        },
        "rows": rows,
    }
    atomic_write_json(run_dir / "scores.json", scores)
    print(f"scored {len(rows)} judgments -> {run_dir / 'scores.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

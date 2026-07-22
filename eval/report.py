#!/usr/bin/env python3
"""Create a per-model, three-arm Markdown report with conservative verdicts."""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys
from typing import Any, Iterable

from benchmark_lib import EVAL_ROOT, load_yaml, sha256_bytes, verify_hashes


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    half_width = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def summarize(rows: Iterable[dict[str, Any]]) -> tuple[int, int, float, tuple[float, float]]:
    materialized = list(rows)
    successes = sum(int(row["pass"]) for row in materialized)
    total = len(materialized)
    rate = successes / total if total else 0.0
    return successes, total, rate, wilson(successes, total)


def comparison_verdict(
    current: tuple[int, int, float, tuple[float, float]],
    candidate: tuple[int, int, float, tuple[float, float]],
    current_hard_fails: int,
    candidate_hard_fails: int,
) -> str:
    if candidate_hard_fails > current_hard_fails:
        return "V5 REGRESSION (hard-fail)"
    if current[1] == 0 or candidate[1] == 0:
        return "missing data"
    if candidate[3][0] > current[3][1]:
        return "V5 wins"
    if current[3][0] > candidate[3][1]:
        return "V4 wins"
    return "inconclusive"


def _fraction(summary: tuple[int, int, float, tuple[float, float]]) -> str:
    return f"{summary[0]}/{summary[1]} ({summary[2]:.0%})"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _hard_fail_count(rows: Iterable[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("hard_fail") and not row["pass"])


def _metrics(run_dir: pathlib.Path, manifest: dict[str, Any]) -> list[str]:
    cells: dict[tuple[str, str], dict[str, Any]] = collections.defaultdict(
        lambda: {"calls": 0, "input": 0, "output": 0, "usage_calls": 0, "latency": 0.0}
    )
    for job in manifest["jobs"].values():
        if job.get("status") != "completed":
            continue
        data = json.loads((run_dir / job["response_path"]).read_text())
        cell = cells[(job["model_name"], job["condition"])]
        cell["calls"] += 1
        cell["latency"] += float(data.get("latency_seconds") or 0)
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if isinstance(input_tokens, int) or isinstance(output_tokens, int):
            cell["usage_calls"] += 1
            cell["input"] += int(input_tokens or 0)
            cell["output"] += int(output_tokens or 0)
    lines = [
        "| Model | Arm | Calls | Input tokens | Output tokens | Avg latency |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for (model, condition), cell in sorted(cells.items()):
        input_value = str(cell["input"]) if cell["usage_calls"] else "n/a"
        output_value = str(cell["output"]) if cell["usage_calls"] else "n/a"
        latency = cell["latency"] / cell["calls"] if cell["calls"] else 0
        lines.append(
            f"| {model} | {condition} | {cell['calls']} | {input_value} | "
            f"{output_value} | {latency:.2f}s |"
        )
    return lines


def build_report(run_dir: pathlib.Path) -> str:
    meta = json.loads((run_dir / "run_meta.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    scores = json.loads((run_dir / "scores.json").read_text())
    root = run_dir / "artifacts"
    integrity_errors = verify_hashes(root, meta.get("artifact_hashes", {}))
    for filename, expected in (meta.get("runner_hashes") or {}).items():
        current = EVAL_ROOT / filename
        if not current.is_file() or sha256_bytes(current.read_bytes()) != expected:
            integrity_errors.append(f"runner drift: {filename}")
    if scores.get("manifest_sha256") != sha256_bytes((run_dir / "manifest.json").read_bytes()):
        integrity_errors.append("manifest changed after scoring")
    for job in manifest["jobs"].values():
        if job.get("status") != "completed":
            continue
        response_path = run_dir / job["response_path"]
        if not response_path.is_file() or sha256_bytes(response_path.read_bytes()) != job.get(
            "response_sha256"
        ):
            integrity_errors.append(f"response hash mismatch: {job['job_id']}")
    if integrity_errors:
        raise ValueError("Run integrity check failed:\n  " + "\n  ".join(integrity_errors))
    config = load_yaml(root / "config.yaml")
    rows = scores["rows"]
    models = sorted({row["model_name"] for row in rows})
    categories = sorted({row["category"] for row in rows})
    condition_labels = {item["id"]: item["label"] for item in config["conditions"]}
    scoring = config["scoring"]
    baseline = scoring["baseline_condition"]
    current = scoring["current_condition"]
    candidate = scoring["candidate_condition"]

    lines = [
        f"# {meta['benchmark_name']} — {meta['profile']} report",
        "",
        f"- Run ID: `{meta['run_id']}`",
        f"- Frozen: `{meta['frozen']}`",
        f"- Freeze ID: `{meta.get('freeze_id') or 'none'}`",
        f"- Score file complete: `{scores.get('complete', False)}`",
        f"- Judge version: `{scores['judge_version']}`",
        "- Primary comparison: within-model V5 minus V4; this is not a raw model leaderboard.",
        "",
        "## Overall by model",
        "",
        "| Model | Bare | V4 | V5 | V5−V4 | Hard fails V4→V5 | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for model in models:
        by_condition: dict[str, list[dict[str, Any]]] = {
            condition: [
                row for row in rows if row["model_name"] == model and row["condition"] == condition
            ]
            for condition in condition_labels
        }
        summaries = {
            condition: summarize(condition_rows)
            for condition, condition_rows in by_condition.items()
        }
        current_hf = _hard_fail_count(by_condition[current])
        candidate_hf = _hard_fail_count(by_condition[candidate])
        delta = summaries[candidate][2] - summaries[current][2]
        verdict = comparison_verdict(
            summaries[current], summaries[candidate], current_hf, candidate_hf
        )
        lines.append(
            f"| {model} | {_fraction(summaries[baseline])} | "
            f"{_fraction(summaries[current])} | {_fraction(summaries[candidate])} | "
            f"{delta:+.1%} | {current_hf}→{candidate_hf} | {verdict} |"
        )

    lines.extend(
        [
            "",
            "Verdicts require non-overlapping Wilson 95% confidence intervals. "
            "A hard-fail regression overrides the interval verdict.",
            "",
            "## Category breakdown",
            "",
            "| Model | Category | Bare | V4 | V5 | V5−V4 | Hard fails V4→V5 | Verdict |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for model in models:
        for category in categories:
            scoped = [
                row
                for row in rows
                if row["model_name"] == model and row["category"] == category
            ]
            by_condition = {
                condition: [row for row in scoped if row["condition"] == condition]
                for condition in condition_labels
            }
            summaries = {
                condition: summarize(condition_rows)
                for condition, condition_rows in by_condition.items()
            }
            current_hf = _hard_fail_count(by_condition[current])
            candidate_hf = _hard_fail_count(by_condition[candidate])
            delta = summaries[candidate][2] - summaries[current][2]
            verdict = comparison_verdict(
                summaries[current], summaries[candidate], current_hf, candidate_hf
            )
            lines.append(
                f"| {model} | {category} | {_fraction(summaries[baseline])} | "
                f"{_fraction(summaries[current])} | {_fraction(summaries[candidate])} | "
                f"{delta:+.1%} | {current_hf}→{candidate_hf} | {verdict} |"
            )

    lines.extend(
        [
            "",
            "## Over-triggering on negative cases",
            "",
            "False-positive rate is `1 − pass rate` on negative/anti-trigger cases.",
            "",
            "| Model | Category | V4 false-positive | V5 false-positive | Delta |",
            "|---|---|---:|---:|---:|",
        ]
    )
    negative_found = False
    for model in models:
        for category in categories:
            negative = [
                row
                for row in rows
                if row["model_name"] == model
                and row["category"] == category
                and row["polarity"] == "negative"
            ]
            current_summary = summarize(row for row in negative if row["condition"] == current)
            candidate_summary = summarize(row for row in negative if row["condition"] == candidate)
            if not current_summary[1] and not candidate_summary[1]:
                continue
            negative_found = True
            current_fpr = 1 - current_summary[2] if current_summary[1] else None
            candidate_fpr = 1 - candidate_summary[2] if candidate_summary[1] else None
            delta = (
                candidate_fpr - current_fpr
                if candidate_fpr is not None and current_fpr is not None
                else None
            )
            lines.append(
                f"| {model} | {category} | {_percent(current_fpr)} | "
                f"{_percent(candidate_fpr)} | "
                f"{'n/a' if delta is None else f'{delta:+.1%}'} |"
            )
    if not negative_found:
        lines.append("| — | — | n/a | n/a | n/a |")

    threshold = float(scoring.get("low_judge_agreement_threshold", 0.90))
    low_agreement = {
        key: value
        for key, value in scores.get("judge_self_agreement", {}).items()
        if value < threshold
    }
    lines.extend(
        [
            "",
            "## Judge reliability",
            "",
            f"Criteria below {threshold:.0%} self-agreement: "
            + (
                ", ".join(f"`{key}`={value:.1%}" for key, value in low_agreement.items())
                if low_agreement
                else "none"
            ),
            "",
            "Self-agreement measures consistency, not correctness. Human audit remains required.",
            "",
            "## API usage and latency",
            "",
            *_metrics(run_dir, manifest),
            "",
            "## Required human audit before adoption",
            "",
            "- [ ] Read every hard-fail response.",
            "- [ ] Read all criteria that are 0% or 100% across every arm.",
            "- [ ] Read every V4/V5 case producing a non-inconclusive verdict.",
            "- [ ] Randomly audit at least 10 PASS judgments.",
            "- [ ] Record judge error rate; target below 5%.",
            "- [ ] Keep development and holdout conclusions separate.",
            "",
            "## Interpretation limits",
            "",
            "This benchmark sends one text turn without live tools. Autonomy, failure, "
            "engineering-safety, and startup findings therefore measure stated behavior, "
            "not enacted tool behavior. Confirm those categories with an agentic test slice.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).expanduser().resolve()
    report = build_report(run_dir)
    output = run_dir / "report.md"
    output.write_text(report)
    print(report, end="")
    print(f"\nwritten: {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

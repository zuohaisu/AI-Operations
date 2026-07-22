#!/usr/bin/env python3
"""Generate blinded multi-model responses for the three-arm benchmark."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import sys
from typing import Any

from benchmark_lib import (
    EVAL_ROOT,
    artifact_files,
    atomic_write_json,
    case_hash,
    conditions_by_id,
    copy_benchmark_artifacts,
    load_cases,
    load_prompt,
    load_yaml,
    model_fingerprint,
    public_model_config,
    relative_hashes,
    runtime_model_config,
    select_cases,
    sha256_bytes,
    sha256_text,
    stable_hash,
    user_content,
    validate_config,
    verify_hashes,
)
from model_client import ModelAPIError, generate


def _freeze_root(raw: str) -> pathlib.Path:
    direct = pathlib.Path(raw).expanduser()
    if direct.is_dir():
        return direct.resolve()
    return (EVAL_ROOT / "freezes" / raw).resolve()


def _source(args: argparse.Namespace) -> tuple[pathlib.Path, dict[str, Any] | None]:
    if not args.freeze:
        config_path = pathlib.Path(args.config).expanduser().resolve()
        if config_path.name != "config.yaml":
            raise ValueError("Custom config must be named config.yaml so snapshots stay relocatable")
        return config_path.parent, None
    root = _freeze_root(args.freeze)
    manifest_path = root / "freeze_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Freeze manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    errors = verify_hashes(root, manifest["artifact_hashes"])
    recalculated = stable_hash(
        {
            "artifacts": manifest.get("artifact_hashes", {}),
            "runner": manifest.get("runner_hashes", {}),
            "models": manifest.get("model_fingerprints", {}),
            "judge": manifest.get("judge_fingerprint", {}),
        }
    )
    if recalculated != manifest.get("combined_hash"):
        errors.append("freeze combined hash mismatch")
    if not manifest.get("freeze_id", "").endswith(recalculated[:12]):
        errors.append("freeze ID does not match combined hash")
    for filename, expected in manifest.get("runner_hashes", {}).items():
        current = EVAL_ROOT / filename
        if not current.is_file() or sha256_bytes(current.read_bytes()) != expected:
            errors.append(f"runner drift: {filename}")
    if errors:
        raise ValueError("Invalid freeze:\n  " + "\n  ".join(errors))
    return root, manifest


def _selected_models(config: dict[str, Any], raw: str) -> list[str]:
    available = list(config["models"])
    if raw == "all":
        return available
    selected = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in selected if item not in config["models"]]
    if unknown:
        raise ValueError(f"Unknown models: {', '.join(unknown)}")
    return selected


def _jobs(
    root: pathlib.Path,
    config: dict[str, Any],
    profile_name: str,
    model_names: list[str],
    model_fingerprints: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    profile = config["profiles"][profile_name]
    cases = select_cases(load_cases(root, config), profile)
    conditions = conditions_by_id(config)
    prompt_hashes = {
        condition_id: sha256_text(load_prompt(root, condition) or "")
        for condition_id, condition in conditions.items()
    }
    jobs: list[dict[str, Any]] = []
    for model_name in model_names:
        raw_model = config["models"][model_name]
        generation = dict(config["generation"])
        generation.update(raw_model.get("generation", {}))
        unresolved_model = {
            key: value
            for key, value in raw_model.items()
            if key not in {"api_key", "headers"} and not key.endswith("_env")
        }
        public_model = (
            model_fingerprints[model_name]
            if model_fingerprints and model_name in model_fingerprints
            else unresolved_model
        )
        for case in cases:
            current_case_hash = case_hash(root, config, case)
            for condition_id in conditions:
                for run_index in range(int(profile["runs_per_cell"])):
                    identity = {
                        "model_name": model_name,
                        "model_config": public_model,
                        "condition": condition_id,
                        "prompt_hash": prompt_hashes[condition_id],
                        "case": case["id"],
                        "case_hash": current_case_hash,
                        "run": run_index,
                        "generation": generation,
                    }
                    jobs.append(
                        {
                            **identity,
                            "job_id": stable_hash(identity)[:24],
                            "status": "pending",
                        }
                    )
    random.Random(int(config["generation"].get("random_seed", 42))).shuffle(jobs)
    return jobs


def _print_dry_run(
    config: dict[str, Any], profile_name: str, model_names: list[str], jobs: list[dict[str, Any]]
) -> int:
    profile = config["profiles"][profile_name]
    case_count = len({job["case"] for job in jobs})
    print(f"benchmark={config['benchmark_name']}")
    print(f"profile={profile_name} runs_per_cell={profile['runs_per_cell']}")
    print(f"models={len(model_names)} conditions=3 cases={case_count} jobs={len(jobs)}")
    any_missing = False
    for model_name in model_names:
        runtime, missing = runtime_model_config(model_name, config["models"][model_name])
        model_id = runtime.get("model_id") or "<unset>"
        suffix = f" MISSING={','.join(missing)}" if missing else " ready"
        print(f"  {model_name}: adapter={runtime.get('adapter')} model_id={model_id}{suffix}")
        any_missing = any_missing or bool(missing)
    if any_missing:
        print("dry-run only: set the listed environment variables before live generation")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(EVAL_ROOT / "config.yaml"))
    parser.add_argument("--profile", default="pilot")
    parser.add_argument("--models", default="all", help="all or comma-separated config names")
    parser.add_argument("--freeze", help="freeze ID or path; required by frozen profiles")
    parser.add_argument("--run-id", help="explicit ID for a resumable run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root, freeze_manifest = _source(args)
    config = load_yaml(root / "config.yaml")
    validate_config(root, config)
    if args.profile not in config["profiles"]:
        raise ValueError(f"Unknown profile: {args.profile}")
    profile = config["profiles"][args.profile]
    if profile.get("require_freeze") and not freeze_manifest:
        raise ValueError(f"Profile {args.profile} requires --freeze")
    model_names = _selected_models(config, args.models)
    runtimes: dict[str, dict[str, Any]] = {}
    missing_runtime: dict[str, list[str]] = {}
    for model_name in model_names:
        runtime, missing = runtime_model_config(model_name, config["models"][model_name])
        runtimes[model_name] = runtime
        if missing:
            missing_runtime[model_name] = missing
    jobs = _jobs(
        root,
        config,
        args.profile,
        model_names,
        {name: model_fingerprint(runtime) for name, runtime in runtimes.items()},
    )
    if args.dry_run:
        return _print_dry_run(config, args.profile, model_names, jobs)
    if missing_runtime:
        lines = [f"{name}: {', '.join(values)}" for name, values in missing_runtime.items()]
        raise ValueError("Missing model environment variables:\n  " + "\n  ".join(lines))
    if freeze_manifest:
        frozen_models = freeze_manifest.get("model_fingerprints", {})
        mismatches = [
            name
            for name in model_names
            if frozen_models.get(name) != model_fingerprint(runtimes[name])
        ]
        if mismatches:
            raise ValueError(
                "Runtime model configuration differs from freeze: "
                + ", ".join(mismatches)
            )

    live_hashes = relative_hashes(root, artifact_files(root, config))
    matrix_hash = stable_hash(
        {
            "artifacts": live_hashes,
            "freeze": freeze_manifest.get("combined_hash") if freeze_manifest else None,
            "profile": args.profile,
            "models": model_names,
            "jobs": [job["job_id"] for job in jobs],
        }
    )
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"{timestamp}-{args.profile}-{matrix_hash[:8]}"
    run_dir = EVAL_ROOT / "out" / run_id
    meta_path = run_dir / "run_meta.json"
    if meta_path.exists():
        previous_meta = json.loads(meta_path.read_text())
        if previous_meta.get("matrix_hash") != matrix_hash:
            raise ValueError(f"Run ID {run_id} already exists with a different matrix")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        copy_benchmark_artifacts(root, run_dir / "artifacts")
        atomic_write_json(
            meta_path,
            {
                "schema_version": 2,
                "run_id": run_id,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "benchmark_name": config["benchmark_name"],
                "profile": args.profile,
                "frozen": bool(freeze_manifest),
                "freeze_id": freeze_manifest.get("freeze_id") if freeze_manifest else None,
                "freeze_hash": freeze_manifest.get("combined_hash") if freeze_manifest else None,
                "judge_fingerprint": (
                    freeze_manifest.get("judge_fingerprint") if freeze_manifest else None
                ),
                "runner_hashes": (
                    freeze_manifest.get("runner_hashes") if freeze_manifest else None
                ),
                "matrix_hash": matrix_hash,
                "artifact_hashes": live_hashes,
                "models": {
                    name: public_model_config(runtimes[name]) for name in model_names
                },
                "conditions": config["conditions"],
            },
        )

    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        known = manifest.get("jobs", {})
    else:
        known = {}
        manifest = {"schema_version": 2, "run_id": run_id, "jobs": known}
    for job in jobs:
        known.setdefault(job["job_id"], job)
    atomic_write_json(manifest_path, manifest)

    cases = {case["id"]: case for case in load_cases(root, config)}
    conditions = conditions_by_id(config)
    failures = 0
    for index, job in enumerate(jobs, 1):
        job_id = job["job_id"]
        response_path = run_dir / "responses" / f"{job_id}.json"
        if response_path.exists():
            response_hash = sha256_bytes(response_path.read_bytes())
            expected_hash = known[job_id].get("response_sha256")
            if expected_hash and expected_hash != response_hash:
                raise ValueError(f"Response hash mismatch: {response_path}")
            known[job_id]["status"] = "completed"
            known[job_id]["response_path"] = str(response_path.relative_to(run_dir))
            known[job_id]["response_sha256"] = response_hash
            continue
        case = cases[job["case"]]
        condition = conditions[job["condition"]]
        system_prompt = load_prompt(root, condition)
        generation = dict(config["generation"])
        generation.update(config["models"][job["model_name"]].get("generation", {}))
        try:
            result = generate(
                runtimes[job["model_name"]],
                system_prompt,
                user_content(root, config, case),
                generation,
            )
            atomic_write_json(
                response_path,
                {
                    "schema_version": 2,
                    "job": {key: value for key, value in job.items() if key != "status"},
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    **result,
                },
            )
            known[job_id]["status"] = "completed"
            known[job_id]["response_path"] = str(response_path.relative_to(run_dir))
            known[job_id]["response_sha256"] = sha256_bytes(response_path.read_bytes())
            known[job_id].pop("error", None)
            print(
                f"[{index}/{len(jobs)}] {job['model_name']} "
                f"{job['condition']} {job['case']} r{job['run']}"
            )
        except ModelAPIError as error:
            failures += 1
            known[job_id]["status"] = "error"
            known[job_id]["error"] = str(error)
            print(f"ERROR {job['model_name']} {job['condition']} {job['case']}: {error}", file=sys.stderr)
        atomic_write_json(manifest_path, manifest)

    atomic_write_json(manifest_path, manifest)
    completed = sum(1 for item in known.values() if item.get("status") == "completed")
    print(f"run_id={run_id} completed={completed}/{len(jobs)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

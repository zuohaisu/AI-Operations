#!/usr/bin/env python3
"""Create and verify immutable-by-hash benchmark snapshots."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import shutil
import sys

from benchmark_lib import (
    EVAL_ROOT,
    RUNNER_FILES,
    artifact_files,
    atomic_write_json,
    copy_benchmark_artifacts,
    load_yaml,
    model_fingerprint,
    relative_hashes,
    runtime_model_config,
    sha256_bytes,
    stable_hash,
    validate_config,
    verify_hashes,
)
from build_v5 import OUTPUT as V5_OUTPUT
from build_v5 import compose as compose_v5


def _slug(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    if not result:
        raise ValueError("Freeze name must contain a letter or number")
    return result


def _resolve_freeze(raw: str, output_root: pathlib.Path) -> pathlib.Path:
    direct = pathlib.Path(raw).expanduser()
    return direct.resolve() if direct.is_dir() else (output_root / raw).resolve()


def _verify(root: pathlib.Path) -> list[str]:
    manifest_path = root / "freeze_manifest.json"
    if not manifest_path.is_file():
        return [f"missing: {manifest_path}"]
    manifest = json.loads(manifest_path.read_text())
    errors = verify_hashes(root, manifest.get("artifact_hashes", {}))
    errors.extend(verify_hashes(root / "runner", manifest.get("runner_hashes", {})))
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
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", help="human-readable name for a new freeze")
    parser.add_argument("--verify", help="freeze ID or path to verify")
    parser.add_argument("--config", default=str(EVAL_ROOT / "config.yaml"))
    parser.add_argument("--output-root", default=str(EVAL_ROOT / "freezes"))
    args = parser.parse_args()
    output_root = pathlib.Path(args.output_root).expanduser().resolve()

    if args.verify:
        root = _resolve_freeze(args.verify, output_root)
        errors = _verify(root)
        if errors:
            print("INVALID\n  " + "\n  ".join(errors), file=sys.stderr)
            return 1
        print(f"OK: {root}")
        return 0
    if not args.name:
        parser.error("--name is required when creating a freeze")

    config_path = pathlib.Path(args.config).expanduser().resolve()
    if config_path.name != "config.yaml":
        raise ValueError("Custom config must be named config.yaml so snapshots stay relocatable")
    source_root = config_path.parent
    config = load_yaml(config_path)
    validate_config(source_root, config)
    if not V5_OUTPUT.is_file() or V5_OUTPUT.read_text() != compose_v5():
        raise ValueError("prompts/v5.md is stale; run python eval/build_v5.py")

    missing_connections: dict[str, list[str]] = {}
    fingerprints: dict[str, dict[str, object]] = {}
    for name, raw in config["models"].items():
        runtime, missing = runtime_model_config(name, raw)
        relevant = [item for item in missing if item != raw.get("api_key_env")]
        if relevant:
            missing_connections[name] = relevant
        fingerprints[name] = model_fingerprint(runtime)
    judge_raw = config["judge"]["model"]
    judge_runtime, judge_missing = runtime_model_config("judge", judge_raw)
    judge_relevant = [item for item in judge_missing if item != judge_raw.get("api_key_env")]
    if judge_relevant:
        missing_connections["judge"] = judge_relevant
    if missing_connections:
        lines = [f"{name}: {', '.join(items)}" for name, items in missing_connections.items()]
        raise ValueError(
            "Set exact base URL and model ID variables before freezing:\n  "
            + "\n  ".join(lines)
        )

    source_artifact_hashes = relative_hashes(
        source_root, artifact_files(source_root, config)
    )
    runner_hashes = {
        filename: sha256_bytes((EVAL_ROOT / filename).read_bytes())
        for filename in RUNNER_FILES
    }
    combined_hash = stable_hash(
        {
            "artifacts": source_artifact_hashes,
            "runner": runner_hashes,
            "models": fingerprints,
            "judge": model_fingerprint(judge_runtime),
        }
    )
    freeze_id = f"{_slug(args.name)}-{combined_hash[:12]}"
    target = output_root / freeze_id
    if target.exists():
        errors = _verify(target)
        if errors:
            raise ValueError(f"Existing freeze is invalid: {target}")
        print(f"already exists: {target}")
        return 0

    copy_benchmark_artifacts(source_root, target)
    runner_target = target / "runner"
    runner_target.mkdir(parents=True)
    for filename in RUNNER_FILES:
        shutil.copy2(EVAL_ROOT / filename, runner_target / filename)
    copied_config = load_yaml(target / "config.yaml")
    artifact_hashes = relative_hashes(target, artifact_files(target, copied_config))
    copied_runner_hashes = {
        filename: sha256_bytes((runner_target / filename).read_bytes())
        for filename in RUNNER_FILES
    }
    atomic_write_json(
        target / "freeze_manifest.json",
        {
            "schema_version": 1,
            "freeze_id": freeze_id,
            "name": args.name,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "combined_hash": combined_hash,
            "artifact_hashes": artifact_hashes,
            "runner_hashes": copied_runner_hashes,
            "model_fingerprints": fingerprints,
            "judge_fingerprint": model_fingerprint(judge_runtime),
        },
    )
    print(f"created freeze_id={freeze_id}")
    print(target)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

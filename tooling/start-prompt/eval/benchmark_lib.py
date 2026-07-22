"""Shared, dependency-light utilities for Benchmark-02."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
from typing import Any

import yaml


EVAL_ROOT = pathlib.Path(__file__).resolve().parent
RUNNER_FILES = (
    "benchmark_lib.py",
    "model_client.py",
    "run.py",
    "judge.py",
    "report.py",
)


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode())


def stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return sha256_bytes(encoded)


def atomic_write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)


def resolve_path(root: pathlib.Path, raw: str) -> pathlib.Path:
    return (root / raw).resolve()


def conditions_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in config["conditions"]}


def load_prompt(root: pathlib.Path, condition: dict[str, Any]) -> str | None:
    raw_path = condition.get("prompt_path")
    if not raw_path:
        return None
    return resolve_path(root, raw_path).read_text()


def load_cases(root: pathlib.Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    path = resolve_path(root, config["artifacts"]["cases"])
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return data


def select_cases(
    cases: list[dict[str, Any]], profile: dict[str, Any]
) -> list[dict[str, Any]]:
    if profile.get("case_ids"):
        wanted = profile["case_ids"]
        by_id = {case["id"]: case for case in cases}
        missing = [case_id for case_id in wanted if case_id not in by_id]
        if missing:
            raise ValueError(f"Unknown profile case IDs: {', '.join(missing)}")
        return [by_id[case_id] for case_id in wanted]
    holdout = bool(profile.get("holdout", False))
    return [case for case in cases if bool(case.get("holdout", False)) == holdout]


def user_content(root: pathlib.Path, config: dict[str, Any], case: dict[str, Any]) -> str:
    text = case["prompt"]
    if "attachment" not in case:
        return text
    cases_path = resolve_path(root, config["artifacts"]["cases"])
    attachment_path = cases_path.parent / case["attachment"]
    attachment = attachment_path.read_text()
    return (
        f"<attachment name='{case['attachment']}'>\n{attachment}\n</attachment>"
        f"\n\n{text}"
    )


def case_hash(root: pathlib.Path, config: dict[str, Any], case: dict[str, Any]) -> str:
    payload: dict[str, Any] = {"case": case}
    if "attachment" in case:
        cases_path = resolve_path(root, config["artifacts"]["cases"])
        attachment = cases_path.parent / case["attachment"]
        payload["attachment_sha256"] = sha256_bytes(attachment.read_bytes())
    return stable_hash(payload)


def validate_config(root: pathlib.Path, config: dict[str, Any]) -> None:
    if config.get("schema_version") != 2:
        raise ValueError("config.yaml must use schema_version: 2")
    conditions = config.get("conditions", [])
    ids = [item.get("id") for item in conditions]
    if ids != ["A", "B", "C"]:
        raise ValueError("Primary conditions must be exactly A=bare, B=v4, C=v5")
    if conditions[0].get("prompt_path"):
        raise ValueError("Condition A must not have a prompt")
    for condition in conditions[1:]:
        path = resolve_path(root, condition["prompt_path"])
        if not path.is_file():
            raise FileNotFoundError(path)
    cases = load_cases(root, config)
    seen_cases: set[str] = set()
    seen_criteria: set[str] = set()
    cases_path = resolve_path(root, config["artifacts"]["cases"])
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in seen_cases:
            raise ValueError(f"Missing or duplicate case ID: {case_id}")
        seen_cases.add(case_id)
        if "attachment" in case and not (cases_path.parent / case["attachment"]).is_file():
            raise FileNotFoundError(cases_path.parent / case["attachment"])
        if case.get("polarity", "positive") not in {"positive", "negative"}:
            raise ValueError(f"Invalid polarity for {case_id}")
        for criterion in case.get("criteria", []):
            criterion_id = criterion.get("id")
            if not criterion_id or criterion_id in seen_criteria:
                raise ValueError(f"Missing or duplicate criterion ID: {criterion_id}")
            seen_criteria.add(criterion_id)
    for profile_name, profile in config.get("profiles", {}).items():
        if int(profile.get("runs_per_cell", 0)) < 1:
            raise ValueError(f"Profile {profile_name} needs runs_per_cell >= 1")
        select_cases(cases, profile)
    if not config.get("models"):
        raise ValueError("At least one target model is required")


def runtime_model_config(name: str, raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    runtime = dict(raw)
    missing: list[str] = []
    for field in ("base_url", "api_key", "model_id"):
        env_name = raw.get(f"{field}_env")
        value = raw.get(field)
        if env_name:
            value = os.getenv(env_name)
            if not value:
                missing.append(env_name)
        elif not value:
            missing.append(f"{name}.{field}")
        runtime[field] = value
    runtime["name"] = name
    return runtime, missing


def public_model_config(runtime: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in runtime.items()
        if key not in {"api_key", "headers", "base_url"} and not key.endswith("_env")
    }
    if runtime.get("base_url"):
        public["base_url_sha256"] = sha256_text(runtime["base_url"])
    return public


def model_fingerprint(runtime: dict[str, Any]) -> dict[str, Any]:
    public = public_model_config(runtime)
    allowed = {
        "adapter",
        "model_id",
        "base_url_sha256",
        "endpoint_path",
        "system_mode",
        "supports_temperature",
        "max_tokens_field",
        "extra_body",
        "extra_headers",
        "api_key_header",
        "api_key_prefix",
        "anthropic_version",
    }
    return {key: public[key] for key in sorted(public) if key in allowed}


def artifact_files(root: pathlib.Path, config: dict[str, Any]) -> list[pathlib.Path]:
    files = [
        root / "config.yaml",
        resolve_path(root, config["artifacts"]["scoring_contract"]),
        resolve_path(root, config["artifacts"]["cases"]),
    ]
    cases_dir = resolve_path(root, config["artifacts"]["cases"]).parent
    files.extend(path for path in sorted(cases_dir.iterdir()) if path.is_file())
    for condition in config["conditions"]:
        if condition.get("prompt_path"):
            files.append(resolve_path(root, condition["prompt_path"]))
    return sorted(set(files))


def relative_hashes(root: pathlib.Path, files: list[pathlib.Path]) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_bytes(path.read_bytes())
        for path in sorted(files)
    }


def copy_benchmark_artifacts(source_root: pathlib.Path, target_root: pathlib.Path) -> None:
    config = load_yaml(source_root / "config.yaml")
    validate_config(source_root, config)
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "config.yaml", target_root / "config.yaml")
    contract_source = resolve_path(source_root, config["artifacts"]["scoring_contract"])
    contract_target = resolve_path(target_root, config["artifacts"]["scoring_contract"])
    contract_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(contract_source, contract_target)
    cases_source = resolve_path(source_root, config["artifacts"]["cases"]).parent
    cases_target = resolve_path(target_root, config["artifacts"]["cases"]).parent
    shutil.copytree(cases_source, cases_target, dirs_exist_ok=True)
    for condition in config["conditions"]:
        raw_path = condition.get("prompt_path")
        if not raw_path:
            continue
        source = resolve_path(source_root, raw_path)
        target = resolve_path(target_root, raw_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def verify_hashes(root: pathlib.Path, hashes: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for relative, expected in hashes.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
        elif sha256_bytes(path.read_bytes()) != expected:
            errors.append(f"hash mismatch: {relative}")
    return errors

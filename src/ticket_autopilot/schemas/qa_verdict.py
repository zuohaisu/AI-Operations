"""Deterministic validation for the QA verdict contract (spec §9).

Implements the zero-dependency subset of JSON Schema the contract needs
(type, required, properties, items, enum) — same reuse-first tradeoff as the
llm driver using urllib instead of an SDK. Anything that fails validation
must never be treated as PASS (spec §2.4, no false success).
"""

from __future__ import annotations

import json
import os

_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "qa-verdict.schema.json"
)

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def load_schema() -> dict:
    with open(_SCHEMA_PATH) as schema_file:
        return json.load(schema_file)


def _check(value, schema: dict, path: str, errors: list[str]) -> None:
    if "enum" in schema:
        if value not in schema["enum"]:
            errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
        return

    expected = schema.get("type")
    if expected:
        if isinstance(value, bool) and expected in ("integer", "number"):
            errors.append(f"{path}: expected {expected}, got boolean")
            return
        if not isinstance(value, _TYPES[expected]):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return

    if expected == "object":
        for required_key in schema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required property '{required_key}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in value:
                _check(value[key], subschema, f"{path}.{key}", errors)

    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{index}]", errors)


def validate_verdict(verdict) -> tuple[bool, list[str]]:
    if not isinstance(verdict, dict):
        return False, ["verdict payload is not a JSON object"]
    errors: list[str] = []
    _check(verdict, load_schema(), "$", errors)
    return (not errors), errors

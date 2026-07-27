"""Durable run snapshots (runs/<name>-<ts>.json).

VFF is intentionally stateless between runs — a workflow run is fully
determined by (workflow, params, mock mode). We therefore persist a snapshot
*after* a run for audit/inspection, and `--resume` reloads the saved params and
re-executes deterministically (drivers like the closer are idempotent). True
mid-run resumption is out of scope for v0.1.
"""

from __future__ import annotations

import json
import os
import time


def _runs_dir(vff_root: str) -> str:
    d = os.path.join(vff_root, "runs")
    os.makedirs(d, exist_ok=True)
    return d


def save(workflow_name: str, result: dict, params: dict, vff_root: str) -> str:
    path = os.path.join(_runs_dir(vff_root),
                        f"{workflow_name}-{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump({"workflow": workflow_name, "params": params,
                   "result": result}, f, indent=2, ensure_ascii=False)
    return path


def list_runs(vff_root: str) -> list[str]:
    d = _runs_dir(vff_root)
    return sorted(os.path.join(d, f) for f in os.listdir(d)
                  if f.endswith(".json"))

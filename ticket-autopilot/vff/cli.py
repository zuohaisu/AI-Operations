"""VFF command-line entry point.

Usage:
  python -m vff run workflows/ticket-pipeline.yaml --params '{"ticket_id":"..."}'
  python -m vff run workflows/ticket-pipeline.yaml --mock          # headless self-test
  python -m vff run workflows/ticket-pipeline.yaml --mock --params '{"ticket_id":"DEMO-1"}'
  python -m vff runs                                          # list snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import sys

VFF_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from . import engine
from . import store


def _parse_params(raw):
    if not raw:
        return {}
    if os.path.exists(raw):
        return json.load(open(raw))
    return json.loads(raw)


def _cmd_run(args):
    wf = json.load(open(args.workflow)) if args.workflow.endswith(".json") \
        else _yaml_load(args.workflow)
    params = _parse_params(args.params)
    eng = engine.Engine(wf, mock=args.mock)
    result = eng.run(params)
    print(json.dumps(result["log"], indent=2, ensure_ascii=False))
    print("\nRETRIES:", dict(result["retry_count"]))
    print("COMPLETED:", result["completed"])
    if result["not_completed"]:
        print("NOT COMPLETED (stalled):", result["not_completed"])
    path = store.save(wf.get("name", "workflow"), result, params, VFF_ROOT)
    print("SNAPSHOT:", path)


def _cmd_runs(args):
    for p in store.list_runs(VFF_ROOT):
        print(p)


def _yaml_load(path):
    import yaml
    return yaml.safe_load(open(path))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vff", description="Vivarium Forge Flow")
    sub = ap.add_subparsers(dest="cmd")

    runp = sub.add_parser("run", help="run a workflow")
    runp.add_argument("workflow", help="path to workflow YAML (or JSON)")
    runp.add_argument("--params", help="JSON string or path to JSON file")
    runp.add_argument("--mock", action="store_true",
                      help="use mock drivers (no LLM/CLI/Plane calls)")
    runp.set_defaults(func=_cmd_run)

    sub.add_parser("runs", help="list run snapshots").set_defaults(func=_cmd_runs)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""VFF engine: declarative workflow interpreter.

Two edge kinds:
  - forward (default): defines a node's `needs` (must complete before the
    target may run). Firing also marks the target stale so it re-runs when an
    upstream re-runs.
  - loop (kind: loop): a back-edge used for retry loops (e.g. verify rejected
    -> re-run execute). It does NOT define `needs`; it only marks the target
    stale. Carries `when` (condition) and `max_retries`.

Readiness model (supports loops without infinite re-running):
  - every node starts `stale = True`
  - a node is ready iff all its forward `needs` are completed AND it is stale
    AND it is not currently running
  - when a node completes, every node that is a *direct* target of ANY of its
    outgoing edges (forward or loop) becomes stale again
This makes execute re-run after verify->execute fires, verify re-run after
execute->verify fires, and naturally terminates on accept.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from . import drivers


class WorkflowError(Exception):
    pass


# ----------------------------------------------------------------------------
# small expression / template helpers
# ----------------------------------------------------------------------------

def _make_ctx(node_outputs: dict, params: dict, vars_: dict, retry: dict):
    nodes_ns = {}
    for nid, val in node_outputs.items():
        nodes_ns[nid] = SimpleNamespace(**val) if isinstance(val, dict) else val
    return SimpleNamespace(nodes=SimpleNamespace(**nodes_ns),
                           params=SimpleNamespace(**params),
                           vars=SimpleNamespace(**vars_),
                           retry=retry)


def _eval(expr: str, ctx) -> bool:
    # trusted: the workflow YAML is authored by the user/team.
    return eval(expr, {"__builtins__": {}}, ctx.__dict__)


def _resolve(value, ctx):
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            return _eval(value[2:-1], ctx)
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    return value


# ----------------------------------------------------------------------------
# engine
# ----------------------------------------------------------------------------

class Engine:
    def __init__(self, workflow: dict, mock: bool = False, hooks: dict | None = None):
        self.wf = workflow
        self.mock = mock
        self.hooks = hooks or {}
        self.agents = workflow.get("agents", {})
        self.edges = workflow.get("edges", [])
        self.vars = workflow.get("vars", {})
        self.params_spec = workflow.get("params", {})
        self.mock_cfg = workflow.get("mock", {})
        self._mock_attempts: dict[str, int] = {}

        # forward needs per node (loop edges excluded)
        self.needs: dict[str, list[str]] = {}
        for e in self.edges:
            if e.get("kind", "forward") == "forward":
                self.needs.setdefault(e["to"], []).append(e["from"])

    # -- public --------------------------------------------------------------

    def run(self, params: dict | None = None, max_steps: int = 500) -> dict:
        params = params or {}
        node_ids = [n["id"] for n in self.wf["nodes"]]
        outputs: dict[str, object] = {}
        completed: set[str] = set()
        fired: set[int] = set()
        retry_count: dict[int, int] = {}
        stale: dict[str, bool] = {nid: True for nid in node_ids}

        log: list[dict] = []
        step = 0
        while True:
            step += 1
            if step > max_steps:
                raise WorkflowError("exceeded max_steps — possible infinite loop")

            ready = [
                n["id"] for n in self.wf["nodes"]
                if stale.get(n["id"], False)
                and all(src in completed for src in self.needs.get(n["id"], []))
            ]
            if not ready:
                break

            for nid in ready:
                node = next(n for n in self.wf["nodes"] if n["id"] == nid)
                self._fire_hook("on_node_start", node, params)
                result = self._run_node(node, outputs, params)
                outputs[nid] = result
                completed.add(nid)
                stale[nid] = False
                log.append({"node": nid, "status": "done", "output": result})
                self._fire_hook("on_node_end", node, result)
                self._fire_edges(node, outputs, params, fired, retry_count, stale)

        terminal = [nid for nid in node_ids if nid not in completed]
        return {
            "completed": sorted(completed),
            "not_completed": terminal,
            "retry_count": retry_count,
            "outputs": outputs,
            "log": log,
        }

    # -- internals -----------------------------------------------------------

    def _fire_hook(self, name: str, *args):
        fn = self.hooks.get(name)
        if fn:
            fn(*args)

    def _fire_edges(self, node, outputs, params, fired, retry_count, stale):
        ctx = _make_ctx(outputs, params, self.vars, retry_count)
        for i, e in enumerate(self.edges):
            if e["from"] != node["id"]:
                continue
            when = e.get("when")
            if when is not None and not _eval(when, ctx):
                continue
            maxr = e.get("max_retries")
            if maxr is not None:
                cap = _resolve(maxr, ctx)
                if retry_count.get(i, 0) >= cap:
                    self._fire_hook("on_retry_exhausted", e, retry_count.get(i, 0))
                    continue
                retry_count[i] = retry_count.get(i, 0) + 1
                self._fire_hook("on_retry", e, retry_count[i])
            fired.add(i)
            stale[e["to"]] = True  # re-run target on any fired edge

    def _run_node(self, node, outputs, params) -> object:
        ctx = _make_ctx(outputs, params, self.vars, {})
        inputs = _resolve(node.get("inputs", {}), ctx)
        agent_name = node.get("agent")
        if not agent_name:
            # no-agent node: pass inputs through as output
            return inputs
        agent = self.agents[agent_name]
        driver = agent.get("driver", "script")

        if self.mock:
            # driver-agnostic canned output (honors `reject_times` so the
            # verify->execute loop can be exercised headless for any driver).
            return self._mock_output(node, agent_name)

        if driver == "llm":
            return drivers.llm_call(agent, inputs, node)
        if driver == "cli":
            return drivers.cli_call(agent, inputs, node, vff_root=_vff_root())
        if driver == "hermes":
            # dispatch a full Hermes sub-agent via the gateway. VFF keeps the
            # deterministic loop + guardrails; Hermes owns execution.
            return drivers.hermes_call(agent, inputs, node, mock=False)
        if driver == "script":
            return drivers.script_call(agent, inputs, vff_root=_vff_root())
        raise WorkflowError(f"unknown driver: {driver}")
        raise WorkflowError(f"unknown driver: {driver}")

    def _mock_output(self, node, agent_name) -> object:
        cfg = self.mock_cfg.get(agent_name, {})
        if "returns" in cfg:
            return cfg["returns"]
        if "reject_times" in cfg:
            key = node["id"]
            self._mock_attempts[key] = self._mock_attempts.get(key, 0) + 1
            if self._mock_attempts[key] <= int(cfg["reject_times"]):
                return {"decision": "reject",
                        "reason": cfg.get("reject_reason",
                                          f"mock reject #{self._mock_attempts[key]}")}
            return {"decision": "accept",
                    "reason": cfg.get("accept_reason", "mock accept after retries")}
        return f"mock output for {node['id']}"


def _vff_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

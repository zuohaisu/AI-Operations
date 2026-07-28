"""Engine drivers — the actual executors behind each node's `agent.driver`.

  - llm   : OpenAI-compatible /chat/completions over urllib (no SDK dep).
            Reads XY_LLM_BASE_URL / XY_LLM_API_KEY / XY_LLM_MODEL from env;
            the agent may override `model`.
  - cli   : spawns an external CLI (default `claude`) in a *strict* sandbox:
              * cwd is forced inside an allowed root (no escaping the dir)
              * a tools allowlist is passed via --allowedTools
              * --permission-mode read-only by default (no writes)
            This is the guardrail the user asked for ("read-only + designated
            directory, strictest first").
  - script: calls a python function in handlers/<entry>.py — used for the
            closer that talks to Plane via plane_client.
  - mock  : handled inside the engine (needs attempt counters); not here.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import urllib.request

DEFAULT_ALLOWED_ROOTS = ["sandbox"]  # relative to engine root; strict default


class SecurityError(Exception):
    pass


# ---------------------------------------------------------------------------
# prompt formatting
# ---------------------------------------------------------------------------

def _format_prompt(inputs: dict) -> str:
    if not inputs:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in inputs.items())


def _maybe_json(text: str, agent: dict):
    if agent.get("expect") == "json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # tolerate fenced blocks
            stripped = text.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("```")[1]
                if stripped.startswith("json"):
                    stripped = stripped[4:]
                return json.loads(stripped)
            raise
    return text


# ---------------------------------------------------------------------------
# llm driver
# ---------------------------------------------------------------------------

def llm_call(agent: dict, inputs: dict, node: dict) -> object:
    base = os.environ.get("XY_LLM_BASE_URL")
    key = os.environ.get("XY_LLM_API_KEY")
    model = agent.get("model") or os.environ.get("XY_LLM_MODEL")
    if not (base and key and model):
        raise RuntimeError(
            "llm driver needs XY_LLM_BASE_URL / XY_LLM_API_KEY / XY_LLM_MODEL "
            f"(missing for agent '{node.get('agent')}')"
        )
    url = base.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": agent.get("system", "")},
            {"role": "user", "content": _format_prompt(inputs)},
        ],
        "temperature": agent.get("temperature", 0.2),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"]
    return _maybe_json(text, agent)


# ---------------------------------------------------------------------------
# hermes driver — dispatch a full Hermes *sub-agent* via the gateway's
# OpenAI-compatible API. One call = "spawn a Hermes agent (with its tools,
# skills, and delegate_task) to do X". This is how the Engine uses Hermes as the
# node-execution backend while keeping the Engine's deterministic loop + guardrails.
#
# Gateway surface (aiohttp, default http://localhost:8642/v1):
#   POST /v1/chat/completions  — OpenAI format, returns agent text (sync)
#   POST /v1/runs              — async run w/ approval gating (future use)
# Auth: HERMES_API_KEY sent as `Authorization: Bearer` (optional). For
# session-scoped memory pass agent.session_key -> X-Hermes-Session-Key.
# ---------------------------------------------------------------------------

def hermes_call(agent: dict, inputs: dict, node: dict, mock: bool = False) -> object:
    prompt = _format_prompt(inputs)
    if mock:
        # exercises the driver integration without a live gateway.
        return {"hermes": True, "note": f"[hermes mock] {prompt[:80]}"}

    base = os.environ.get("HERMES_API_URL", "http://localhost:8642/v1").rstrip("/")
    key = os.environ.get("HERMES_API_KEY")
    model = agent.get("model") or os.environ.get("HERMES_MODEL", "hermes-agent")
    url = base + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": agent.get("system", "")},
            {"role": "user", "content": prompt},
        ],
        "temperature": agent.get("temperature", 0.3),
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    session_key = agent.get("session_key") or os.environ.get("HERMES_SESSION_KEY")
    if session_key:
        headers["X-Hermes-Session-Key"] = session_key

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"]
    return _maybe_json(text, agent)


# ---------------------------------------------------------------------------
# cli driver (strict sandbox)
# ---------------------------------------------------------------------------

def _resolve_within_root(relpath: str, engine_root: str, allowed_roots) -> str:
    roots = [os.path.join(engine_root, r) for r in allowed_roots]
    target = os.path.abspath(os.path.join(engine_root, relpath))
    if not any(os.path.commonpath([target, r]) == r for r in roots):
        raise SecurityError(
            f"cwd '{target}' is outside allowed roots {roots}. "
            "Refusing to spawn CLI outside the designated directory."
        )
    return target


def cli_call(agent: dict, inputs: dict, node: dict, engine_root: str) -> object:
    allowed_roots = agent.get("allowed_roots", DEFAULT_ALLOWED_ROOTS)
    cwd = _resolve_within_root(agent.get("cwd", "sandbox"), engine_root, allowed_roots)

    prompt = _format_prompt(inputs)
    system = agent.get("system", "")

    argv = agent.get("argv")
    if argv:
        # full command template with {prompt}/{cwd}/{system} placeholders —
        # for CLIs whose flag style differs from claude (codex exec, pi).
        if system and not any("{system}" in part for part in argv):
            prompt = f"{system}\n\n{prompt}"
        cmd = [part.replace("{prompt}", prompt)
                   .replace("{cwd}", cwd)
                   .replace("{system}", system)
               for part in argv]
    else:
        command = agent.get("command", "claude")
        permission_mode = agent.get("permission_mode", "read-only")
        tools = agent.get("tools", [])
        # claude expects `--allowedTools a,b`; qodercli expects variadic `--tools a b`.
        tools_flag = agent.get("tools_flag", "--allowedTools")
        tools_as_args = agent.get("tools_as_args", False)

        cmd = [command, "-p", prompt,
               "--permission-mode", permission_mode,
               "--cwd", cwd]
        if tools:
            if tools_as_args:
                cmd += [tools_flag, *tools]
            else:
                cmd += [tools_flag, ",".join(tools)]
        if system:
            cmd += ["--append-system-prompt", system]
        cmd += agent.get("extra_args", [])

    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cli driver ({cmd[0]}) exited {proc.returncode}: {proc.stderr}"
        )
    return _maybe_json(proc.stdout.strip(), agent)


# ---------------------------------------------------------------------------
# script driver
# ---------------------------------------------------------------------------

def script_call(agent: dict, inputs: dict, engine_root: str) -> object:
    entry = agent.get("entry")
    if not entry:
        raise ValueError("script driver requires `entry` (handlers/<entry>.py)")
    handlers_dir = os.path.join(engine_root, "engine", "handlers")
    if handlers_dir not in sys.path:
        sys.path.insert(0, handlers_dir)
    mod = importlib.import_module(entry)
    fn = getattr(mod, entry)
    return fn(**inputs)

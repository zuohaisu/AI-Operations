"""Engine drivers — the actual executors behind each node's `agent.driver`.

  - llm   : OpenAI-compatible /chat/completions over urllib (no SDK dep).
            Reads XY_LLM_BASE_URL / XY_LLM_API_KEY / XY_LLM_MODEL from env;
            the agent may override `model`.
  - cli   : spawns an external CLI (default `claude`) in a *strict* sandbox:
              * cwd is forced inside an allowed root (no escaping the dir)
              * a tools allowlist is passed via --allowedTools
              * the engine-internal permission mode stays read-only by default
                (no writes) and is translated to each CLI's real flag values
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

from .guardrails import (
    DEFAULT_ALLOWED_ROOTS,
    DEFAULT_TOOL_WHITELIST,
    GuardrailPolicy,
    SecurityError,
    RunExecutionContext,
    check_cwd,
    check_permission_mode,
    check_role_boundary,
    check_tools,
)


# The engine's permission vocabulary ("read-only"/"write") is internal; the
# real CLIs only accept their own --permission-mode choices (claude 2.x:
# acceptEdits/auto/bypassPermissions/manual/dontAsk/plan; qodercli 1.x:
# default/plan/auto/bypass_permissions/accept_edits/dont_ask), so passing the
# internal value verbatim makes the CLI exit 1 before the agent even starts.
# Read-only roles omit the flag: in non-interactive -p mode both CLIs deny any
# tool outside the allowlist, so the tools allowlist remains the boundary.
# Unknown commands keep the verbatim pass-through for custom agent CLIs.
_CLI_PERMISSION_MODES: dict[str, dict[str, str | None]] = {
    "claude": {"read-only": None, "write": "acceptEdits"},
    "qodercli": {"read-only": None, "write": "accept_edits"},
}
# claude 2.x has no --cwd flag; subprocess.run(cwd=...) already pins the dir.
_CLI_NO_CWD_FLAG = {"claude"}


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
    """Backward-compatible path helper backed by the shared policy check."""
    return check_cwd(
        relpath,
        engine_root,
        GuardrailPolicy(allowed_roots=list(allowed_roots)),
    )


def _direct_call_policy(agent: dict) -> GuardrailPolicy:
    """Support direct callers while Engine workflow policy remains authoritative."""
    return GuardrailPolicy.from_config({
        "allowed_roots": agent.get("allowed_roots", DEFAULT_ALLOWED_ROOTS),
        "read_only": agent.get("read_only", True),
        "tool_whitelist": agent.get("tool_whitelist", DEFAULT_TOOL_WHITELIST),
    })


def cli_call(agent: dict, inputs: dict, node: dict, engine_root: str,
             policy: GuardrailPolicy | None = None,
             run_context: RunExecutionContext | None = None) -> object:
    """Run a CLI only after deterministic Engine and role guardrail checks pass."""
    policy = policy or _direct_call_policy(agent)
    cwd = check_cwd(agent.get("cwd", "sandbox"), engine_root, policy)
    permission_mode = agent.get("permission_mode", "read-only")
    tools = agent.get("tools", [])
    check_permission_mode(permission_mode, policy)
    check_tools(tools, policy)
    # ``node.agent`` permits simple workflows to name their role by agent name;
    # explicit node/agent role wins and unnamed agents retain AIO-9 behaviour.
    role = node.get("role") or agent.get("role") or node.get("agent")
    check_role_boundary(
        role,
        cwd=cwd,
        permission_mode=permission_mode,
        tools=tools,
        run_context=run_context,
        requested_branch=agent.get("branch"),
    )

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
        # claude expects `--allowedTools a,b`; qodercli expects variadic `--tools a b`.
        tools_flag = agent.get("tools_flag", "--allowedTools")
        tools_as_args = agent.get("tools_as_args", False)

        cmd = [command, "-p", prompt]
        cli_name = os.path.basename(command)
        # A probed catalog choice (agent.cli_permission_mode) wins; otherwise the
        # internal mode is translated to the CLI's own vocabulary.
        cli_mode = (agent.get("cli_permission_mode")
                    or _CLI_PERMISSION_MODES.get(cli_name, {}).get(permission_mode, permission_mode))
        if cli_mode:
            cmd += ["--permission-mode", cli_mode]
        if cli_name not in _CLI_NO_CWD_FLAG:
            cmd += ["--cwd", cwd]
        if tools:
            if tools_as_args:
                cmd += [tools_flag, *tools]
            else:
                cmd += [tools_flag, ",".join(tools)]
        if system:
            cmd += ["--append-system-prompt", system]
        cmd += agent.get("extra_args", [])

    # The Web service is detached from the launching shell.  Never let an Agent
    # CLI inherit a terminal and suspend the Run with SIGTTIN while attempting
    # to read stdin; the complete request is already present in ``cmd``.
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=600,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        # Some CLIs (notably qodercli) write account/model diagnostics to
        # stdout even when they exit non-zero.  Preserve whichever stream has
        # actionable text so a Web HARD_BREAK never renders an empty reason.
        diagnostic = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        if not diagnostic:
            diagnostic = "no diagnostic output"
        raise RuntimeError(
            f"cli driver ({cmd[0]}) exited {proc.returncode}: {diagnostic[:2000]}"
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

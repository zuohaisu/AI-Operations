#!/usr/bin/env python3
"""
orchestrator.py — ticket-driven Plan -> Execute -> Verify -> close pipeline.

Replaces the raft CLI entirely. Agents are plain OpenAI-compatible chat
completions (DeepSeek / GLM / Kimi / OpenAI / any `/v1/chat/completions`
endpoint), driven via urllib (no SDK dependency). Personas are embedded below,
derived from AGENT_PROMPTS.md.

Flow (closed loop, human-in-the-loop verify by default):
    Plane ticket
      -> [Plan Agent]    LLM(system=PLAN_SYSTEM)  -> expect <<<HANDOFF_TO_EXECUTE>>>
      -> [Execute Agent] LLM(system=EXECUTE_SYSTEM)-> expect <<<HANDOFF_TO_VERIFY>>>
      -> Verify:  human approve (default)  OR  auto Verify Agent (--auto-verify)
           approve  -> post Plan+Result as ticket comments, set_state(Done)
           reject   -> feedback back to Execute (retry, up to MAX_RETRY) -> re-verify

LLM config comes from env (or a local .env file):
    XY_LLM_BASE_URL  e.g. https://api.deepseek.com/v1  (versioned base; we append /chat/completions)
    XY_LLM_API_KEY   your key
    XY_LLM_MODEL     e.g. deepseek-chat

Plane integration is PROVEN (plane_client.py: browser UA + `state` field bypass
Cloudflare + the old state_id bug). Run without a key using --dry-run to validate
routing + ticket-close end to end (mock agent replies emit the real signal tokens).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

# Load .env from the script dir if present (gitignored; never commit it).
_DOTENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_DOTENV):
    for line in open(_DOTENV, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from plane_client import get_issue, set_state, add_comment, STATE, delete_issue

PLAN_TIMEOUT = 300                      # max seconds for Plan agent
EXEC_TIMEOUT = 600                      # max seconds for Execute agent
VERIFY_TIMEOUT = 180                    # max seconds for Verify agent
MAX_RETRY = 3                           # human/auto-reject retries before escalation
SIGNAL_RE = re.compile(r"(?m)^<<<([A-Z_]+)>>>$")

# ---------- agent personas (source of truth: AGENT_PROMPTS.md) ----------
PLAN_SYSTEM = """你是「计划 Agent」，在一个由 ticket 驱动的自动化流水线里。
收到一张 Plane ticket（标题 + 描述）后，产出一份**自包含、可执行**的规格说明，供下游「执行 Agent」直接照做。
要求：
- 用 EARS 风格写需求（Ubiquitous/Event-driven/Unwanted/State-driven/Optional）。
- 明确：目标用户、范围（In scope / Out of scope）、验收标准、实现步骤、边界与异常。
- 不要写代码，只产出规格。
当规格完整时，在**最后一行单独**输出标记 <<<HANDOFF_TO_EXECUTE>>>。
若 ticket 含糊或超出范围，不要输出该标记，改为提出需要澄清的问题。"""

EXECUTE_SYSTEM = """你是「执行 Agent」。你收到「计划 Agent」产出的规格说明，负责产出**具体交付物**（代码 / 文档 / 具体改动）。
要求：
- 交付物要具体、完整、可直接使用；若规格有歧义，做合理假设并标注。
- 用清晰的结构呈现：改动摘要、文件清单、关键内容、如何验证。
- 不要提问，直接交付。
当交付物完成时，在**最后一行单独**输出标记 <<<HANDOFF_TO_VERIFY>>>。"""

VERIFY_SYSTEM = """你是「验收 Agent」。你收到原始 ticket、计划规格、以及执行 Agent 的交付物。
判断交付物是否满足规格与 ticket 意图。
- 通过：在**最后一行单独**输出 <<<ACCEPTED>>>。
- 不通过：输出 <<<REJECTED>>>，随后用简短要点列出必须修改的内容。
严格但公正。"""

# ---------- LLM driver (OpenAI-compatible, urllib, zero deps) ----------
def llm_configured():
    return bool(os.environ.get("XY_LLM_BASE_URL") and os.environ.get("XY_LLM_API_KEY")
                and os.environ.get("XY_LLM_MODEL"))

def _chat_url():
    base = os.environ["XY_LLM_BASE_URL"].rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"

def llm_call(system, user, timeout=300):
    """One non-streaming chat completion. Returns the assistant text."""
    url = _chat_url()
    key = os.environ["XY_LLM_API_KEY"]
    model = os.environ["XY_LLM_MODEL"]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected LLM response shape: {json.dumps(resp)[:400]}")

def check_llm():
    if not llm_configured():
        print("LLM not configured. Set these env vars (or put them in .env):")
        print("  XY_LLM_BASE_URL  e.g. https://api.deepseek.com/v1")
        print("  XY_LLM_API_KEY   your key")
        print("  XY_LLM_MODEL     e.g. deepseek-chat")
        return False
    print(f"LLM configured: model={os.environ['XY_LLM_MODEL']} base={_chat_url()}")
    return True

# ---------- dry-run canned replies ----------
DRY_PLAN = """# 目标
为聊天窗口加一个最小自测脚本占位。

# 范围
- In scope: 新增 scripts/smoke.py
- Out of scope: 无

# 验收标准
When 运行 scripts/smoke.py, the system shall 打印 OK。

# 实现步骤
1. 创建 scripts/smoke.py 打印 OK。

<<<HANDOFF_TO_EXECUTE>>>
"""

DRY_EXEC = """# 改动摘要
新增 scripts/smoke.py。

# 文件清单
- scripts/smoke.py（新增）

# 自测结果
python scripts/smoke.py -> OK

# 如何验证
运行脚本看到 OK。

<<<HANDOFF_TO_VERIFY>>>
"""

DRY_VERIFY_ACCEPT = "交付物满足规格，验证通过。\n\n<<<ACCEPTED>>>"

# ---------- pipeline ----------
def _split_signal(text, token):
    """Return (deliverable, matched_bool) splitting on the signal token."""
    parts = text.split(f"<<<{token}>>>")
    return parts[0].strip(), len(parts) > 1

def run_pipeline(ticket_id, dry_run=False, auto_verify=False):
    if not dry_run and not llm_configured():
        sys.exit("LLM not configured. Set XY_LLM_BASE_URL/XY_LLM_API_KEY/XY_LLM_MODEL "
                 "(or add a .env), or use --dry-run.")
    if dry_run:
        print("(dry-run: using mock agents, no LLM calls)")

    print(f"\n=== Pipeline start: ticket {ticket_id} ===")
    issue = get_issue(ticket_id)
    title = issue.get("name")
    desc = issue.get("description_stripped") or issue.get("description_html") or ""
    print(f"ticket: {title}")

    # 1) Plan
    print("\n[Plan Agent] ...")
    plan_input = f"# Ticket: {title}\n\n{desc}"
    plan_out = DRY_PLAN if dry_run else llm_call(PLAN_SYSTEM, plan_input, PLAN_TIMEOUT)
    spec, ok = _split_signal(plan_out, "HANDOFF_TO_EXECUTE")
    if not ok:
        sys.exit("[Plan] no <<<HANDOFF_TO_EXECUTE>>>; abort.")
    print(f"[Plan Agent] spec received ({len(spec)} chars).")

    # 2) Execute (+ retry loop)
    attempts = 0
    while True:
        print("\n[Execute Agent] ... (attempt %d)" % (attempts + 1))
        exec_input = spec if attempts == 0 else (
            f"修订要求：\n{feedback}\n\n原规格：\n{spec}")
        exec_out = DRY_EXEC if dry_run else llm_call(EXECUTE_SYSTEM, exec_input, EXEC_TIMEOUT)
        result, ok = _split_signal(exec_out, "HANDOFF_TO_VERIFY")
        if not ok:
            sys.exit("[Execute] no <<<HANDOFF_TO_VERIFY>>>; abort.")
        print(f"[Execute Agent] result received ({len(result)} chars).")

        # 3) Verify
        if auto_verify:
            print("\n[Verify Agent] ...")
            v_in = f"# Ticket\n{title}\n\n{desc}\n\n# Spec\n{spec}\n\n# Deliverable\n{result}"
            v_out = DRY_VERIFY_ACCEPT if dry_run else llm_call(VERIFY_SYSTEM, v_in, VERIFY_TIMEOUT)
            accepted = "<<<ACCEPTED>>>" in v_out
            print(v_out[-800:])
        else:
            print("\n----- Execute result (for your review) -----")
            print(result[-1500:])
            print("--------------------------------------------")
            accepted = input("Approve and close ticket? [y/N]: ").strip().lower() == "y"

        if accepted:
            _close(ticket_id, spec, result)
            return
        attempts += 1
        if attempts >= MAX_RETRY:
            print(f"=== ESCALATED after {MAX_RETRY} rejects. Ticket left open for human. ===")
            return
        if auto_verify:
            # extract rejection notes as feedback
            feedback = v_out.split("<<<REJECTED>>>")[-1].strip() or "请按验收意见修改。"
        else:
            feedback = input("What must be fixed? (sent back to Execute): ").strip()

def _close(ticket_id, spec, result):
    """Post Plan+Result as comments (best-effort), then close the ticket."""
    print("\n[closing] posting summary comments ...")
    try:
        add_comment(ticket_id, f"## 计划规格 (Plan Agent)\n\n{spec}")
        add_comment(ticket_id, f"## 执行结果 (Execute Agent)\n\n{result}")
        print("[closing] comments posted.")
    except Exception as e:
        print(f"[closing] WARN: comment post failed ({e}); continuing to close.")
    set_state(ticket_id, "done")
    print(f"=== DONE: ticket {ticket_id} closed. ===")

def main():
    ap = argparse.ArgumentParser(description="XY ticket -> Plan -> Execute -> Verify -> close")
    ap.add_argument("ticket_id", nargs="?", help="Plane issue UUID to process")
    ap.add_argument("--dry-run", action="store_true",
                    help="mock agents (no LLM/key needed); validates routing + close")
    ap.add_argument("--auto-verify", action="store_true",
                    help="use a Verify Agent LLM instead of terminal human approval")
    ap.add_argument("--check-llm", action="store_true",
                    help="validate LLM env config, then exit (no pipeline run)")
    args = ap.parse_args()
    if args.check_llm:
        check_llm()
        return
    if not args.ticket_id:
        ap.error("ticket_id is required (or use --check-llm)")
    run_pipeline(args.ticket_id, dry_run=args.dry_run, auto_verify=args.auto_verify)

if __name__ == "__main__":
    main()

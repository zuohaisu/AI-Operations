# ticket-pipeline — ticket → Plan → Execute → (Verify) → 关 ticket 自动化闭环

把一张 Plane ticket 交给 Plan Agent 出规格，转交 Execute Agent 落地，验收（人工或
Verify Agent）后自动写回评论并关 ticket。基于 **OpenAI 兼容 LLM API**（DeepSeek /
GLM / Kimi 任选其一）作 Agent 运行时 + **Plane REST API 直连**绕过 MCP 代理。

> 历史注：本管道最初计划用 raft.build 作 Agent 运行时，但 `raft` 消息 CLI 不公开分发
> （只随 Raft 桌面 App），本机仅有 `raft-computer` 守护进程（另一个二进制，无 message
> 子命令）。2026-07-27 已改为直接调用用户自己的 OpenAI 兼容 key，raft 依赖已移除。

## 文件

| 文件 | 作用 |
|---|---|
| `plane_client.py` | 已验证的 Plane REST 客户端（读/建/改状态/删/**发评论**）。**两个关键坑已内置**：浏览器 UA 绕过 Cloudflare、PATCH 用 `state` 字段而非 `state_id`。 |
| `stepB_verify_plane_api.py` | Step B 验证：建测试 ticket → 改 Done → 回读确认 → 删。证明 REST 直连绕过 Cloudflare。 |
| `AGENT_PROMPTS.md` | Plan / Execute / Verify 三个 Agent 的 persona 设计 + 交接信号契约（orchestrator 内嵌 system prompt 的来源）。 |
| `orchestrator.py` | 编排器本体。Plan→Execute→验收（人工或 `--auto-verify`）→评论写回→关 ticket，含拒绝重试。带 `--dry-run` / `--check-llm`。 |
| `.env.example` | LLM key 配置模板。复制为 `.env` 填入你的 key（`.env` 不要提交）。 |

## 配置（一次性）

```bash
cd src/ticket_autopilot/reference/ticket-pipeline
cp .env.example .env
# 编辑 .env，三选一，例如 DeepSeek：
#   XY_LLM_BASE_URL=https://api.deepseek.com/v1
#   XY_LLM_API_KEY=sk-...
#   XY_LLM_MODEL=deepseek-chat
# GLM:  https://open.bigmodel.cn/api/paas/v4  + glm-4-plus 等
# Kimi: https://api.moonshot.cn/v1            + moonshot-v1-32k 等
```

orchestrator 会在 BASE_URL 后自动拼 `/chat/completions`，零依赖（纯 urllib）。

## 运行

```bash
cd src/ticket_autopilot/reference/ticket-pipeline
PY=/Users/hzuo/.workbuddy/binaries/python/versions/3.13.12/bin/python3

# B) 验证 Plane 直连可用（无副作用，用完删测试 ticket）
$PY stepB_verify_plane_api.py

# 0) 确认 LLM key 配置正确（发一条 ping，打印模型回复）
$PY orchestrator.py --check-llm

# 干跑整条管道（不消耗 LLM 额度，用模拟 Agent 验证路由+评论+关 ticket）
ID=$($PY -c "from plane_client import create_issue; print(create_issue('[PIPELINE-TEST] dry')['id'])")
echo "y" | $PY orchestrator.py "$ID" --dry-run
$PY -c "from plane_client import delete_issue; delete_issue('$ID')"

# 真实运行（人工验收：终端里批准/打回）
$PY orchestrator.py <ticket_id>

# 真实运行（Verify Agent 自动验收，REJECTED 自动打回 Execute 重试）
$PY orchestrator.py <ticket_id> --auto-verify
```

## 流程

1. 读 ticket（`plane_client.get_issue`）→ 拼入 Plan system prompt。
2. **Plan Agent** 产出实施规格，以 `<<<HANDOFF_TO_EXECUTE>>>` 收尾。
3. **Execute Agent** 按规格执行，以 `<<<HANDOFF_TO_VERIFY>>>` 收尾。
4. 验收：默认人工（终端 y/n + 打回意见）；`--auto-verify` 时由 **Verify Agent**
   判 `<<<ACCEPTED>>>` / `<<<REJECTED>>>`，拒绝则带意见回到 Execute（最多重试 `MAX_RETRIES` 次）。
5. 通过后：把 Plan 规格 + Execute 结果作为评论写回 ticket（`add_comment`），再 `set_state → Done`。

## 两个必须先知道的事实（否则会卡）

- **Cloudflare 拦 User-Agent**：`api.plane.so` 对 Python-urllib 默认 UA 返回 403
  (error 1010)。加浏览器 UA 即绕过——这也是之前 MCP 代理 403 的真因。
- **PATCH 状态用 `state` 不是 `state_id`**：`state_id` 在 PATCH 上被静默丢弃（HTTP 200
  但状态不变），这正是一直被当成「MCP bug」的现象。`plane_client.set_state` 已用正确字段。

## 本期未做（后续阶段）

- 自动触发：Plane webhook / 轮询新 ticket（目前手动传 ticket_id）。
- Execute Agent 目前只产出「执行结果描述」，不真正改代码/跑命令（需要接工具调用才是真执行）。
- 最大重试超限后的升级通知机制。

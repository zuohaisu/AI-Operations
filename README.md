# Ticket Autopilot

Ticket Autopilot 是一个供单人本机使用的 **Plane-first Web 控制器**：从一张结构化 Plane Ticket 开始，创建隔离 Worktree，驱动 Developer 与独立只读 QA，最多五轮修复，并只在 QA PASS 后创建本地 feature-branch Commit。

当前 Phase 1 的成功终点是可审计的本地 Commit 和完整 Run evidence；它**不会**自动 Push、创建 PR、Merge、部署或写回 Plane。最终交付节奏由 Repository Owner 决定。

## 现在能做什么

1. 在浏览器中保存本机的 Plane、仓库与三类 Agent CLI 配置。
2. 读取配置 Project 中的未完成 Plane Ticket，并用结构化 ticket contract 判定是否可运行。
3. 使用 `tasks/AIO-NNN-dev-prompt.md` 与 `tasks/AIO-NNN-acceptance-prompt.md`；缺任一 Prompt 时调用 Planner 生成仅属于该 Run 的版本。
4. 创建一个 owned Worktree 与 feature branch，后台按 Developer → deterministic checks → 独立 QA 运行。
5. QA FAIL 时只把原始 findings 交回 Developer；QA 总数最多五轮。QA PASS 后 Controller 才会提交 ticket-owned changed files。
6. 在页面查看 append-only Timeline、Prompt 来源、findings、checks、changed files、worktree、Commit SHA 和 Hard Break。
7. 对失败 Run 执行受约束的 Retry current stage 或 Stop owned Run；页面重开后仍可查看 retained artifacts。
8. 记录 Repository Owner 的 visual accept、override、feature-branch push、Draft PR 或 merge 授权事件。当前仅记录授权，尚不从页面执行远端 GitHub 操作。

## 启动

需要 Python 3.11+、Git，以及已经在 `PATH` 中可调用的 Planner、Developer、QA Agent CLI。

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ticket_autopilot.web start
```

服务仅监听 `http://127.0.0.1:8765/`，启动后会打开浏览器。停止或查看状态：

```bash
python -m ticket_autopilot.web status
python -m ticket_autopilot.web stop
```

首次打开页面时填写：Plane workspace、project ID、API key、目标 Git repository 的绝对路径，以及 Planner / Developer / QA CLI 命令。配置保存在本机 `~/.ticket-autopilot/config.json`，目录权限为 owner-only；页面和日志会掩码 Secret。它是单人本机 Phase 1 设计，不提供 Keychain、多用户或远程访问。

## 一张 Ticket 的实际流程

```text
Plane 未完成 Ticket
  → contract / readiness gate
  → 复用已有 Prompt，或 Planner 生成 Run-owned Prompt
  → isolated worktree + feature branch
  → Developer → checks → independent QA (最多 5 次)
  → PASS 后本地 Commit，或 QA_EXHAUSTED / BLOCKED / HARD_BREAK
  → Timeline、artifacts 和 Owner decision evidence
```

Run artifacts 和 disposable Worktree 均位于被开发仓库的 `.ticket-autopilot/` 下。系统一次只允许同一 repository 的一个 active Run；不会自动选择下一张 Ticket，也不会在服务重启后擅自恢复 Agent 执行。

## 安全与边界

- Developer 和 QA Agent 不得自行 Commit、Push、建 PR、Merge、部署或写回 Plane。
- QA 使用独立的只读上下文；Agent 运行错误、超时、畸形输出和证据不匹配会成为 Hard Break，不伪装成 QA FAIL。
- 归属问题区分 `DIFF_SPLIT_REQUIRED`、`BLOCKED_ATTRIBUTION` 与 `TECHNICAL_BLOCKED`；可机械拆分的 Diff 不应被误报为泛化的 requirements blocker。
- 页面只记录 Owner authorization；真正 feature-branch push、Draft PR、merge 和 Plane 状态写回是后续交付能力，不是当前 Web UI 的副作用。

## 当前已知可靠性问题

服务启动的 `service_id` 可能以 `-` 开头，偶发被命令行误解析，导致本机健康检查超时。该问题已有失败测试覆盖，尚未修复；在它修复前，不能把“单命令稳定启动”视为完成。

## 文档定位

| 文档 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) / [IDEA.md](IDEA.md) | 北极星、Goal check、复用优先与 Owner authority。 |
| [docs/closed-loop-workflow.md](docs/closed-loop-workflow.md) | 当前 Phase 1 的权威操作边界与证据闸。 |
| [specs/Ticket Autopilot PRD.md](specs/Ticket%20Autopilot%20PRD.md) | 历史产品设计与决策背景，不作为当前操作说明。 |
| `tasks/AIO-NNN-*.md` | 每张 Ticket 的 Developer / Acceptance Prompt。 |

`ticket-controller`、Engine YAML 和 reference pipeline 仍保留用于历史能力与后续复用；它们不是当前 Phase 1 Web 操作入口。

## 验证

```bash
.venv/bin/python -m pytest \
  tests/test_web_service.py \
  tests/test_local_config.py \
  tests/test_web_tickets.py \
  tests/test_prompt_resolver.py \
  tests/integration/test_web_agent_loop.py \
  tests/test_web_run_tracking.py \
  tests/integration/test_web_hard_break.py -q
```

测试采用 fake Agent 与临时仓库；它们证明本地控制流和边界，不等同于一次真实 Plane、真实 Agent CLI 或 GitHub 远端交付。

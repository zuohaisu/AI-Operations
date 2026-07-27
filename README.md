# Ticket Autopilot

轻量本地控制器（Lightweight local controller）。把一张结构化的 Linear Ticket 自动跑成
「已通过确定性验证 + 独立 AI QA」的 GitHub Pull Request。

> 仓库文件夹名暂为 `AI-Operations`，项目/工具名为 **Ticket Autopilot**。
> 团队名 VF/VFF 不在本项目中使用。

## 闭环

```
Linear Ticket
  → 手动启动 Controller
  → 隔离 Git Run（worktree + branch）
  → Claude 开发
  → 确定性验证（commit / diff / 测试 exit 0）
  → Controller 自建 PR
  → Codex 独立 QA
  → 最多两轮修复
  → Linear: In Review / Blocked
  → 人工 Review & Merge
```

## 设计原则（取自规格 `specs/Ticket Autopilot v0.1 Specification.md`）

- 确定性动作不委托 LLM（建 worktree、跑测试、建 PR、更新 Linear、清理都由 Controller 完成）
- 只依据证据推进状态，不把 Agent 自述当完成证据
- 一次性 Run，不实现 Resume
- 仅 R0/R1 自动执行；R2/R3 转人工（`BLOCKED_NEEDS_HUMAN`）

## 复用优先（见 `AGENTS.md` / `IDEA.md`）

先盘点 Linear/Plane 自动化、agent hooks、MCP、GitHub Actions、GitHub 原生集成能闭合哪些阶段，
只对验证过的缺口写最薄的胶水/Controller。不预先造自定义平台。

## 开发

```bash
pip install -e .
ticket-controller --help
```

任务票见 `tasks/ticket-autopilot-v0.1-tasklist.md`。

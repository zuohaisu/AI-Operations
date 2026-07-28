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

## 仓库结构（三层命名与职责）

本仓库采用统一的**三层命名**，所有代码/文档以此为准（2026-07-28 决策锁定）：

| 层级 | 名称 | 位置 | 职责 |
|---|---|---|---|
| 产品 | **Ticket Autopilot** | `src/ticket_autopilot/` | 整个产品包（含 CLI `ticket-controller`、规格、业务服务） |
| 引擎 | **Engine** | `src/ticket_autopilot/engine/` | 声明式编排内核：`engine.py`(DAG+重试闭环解释器) / `drivers.py`(llm·cli·hermes·script 执行器+护栏) / `store.py`(快照) / `cli.py`(`python -m ticket_autopilot.engine`) / `handlers/`(仅 `close_ticket.py` 触碰 Plane) |
| 连接器 | **Connector** | `src/ticket_autopilot/connectors/` | 把通用引擎适配到具体外部系统（Linear / Plane / GitHub / Codex）的胶水层 |

```
AI-Operations/
├── README.md / pyproject.toml        # 项目级元信息（产品 = Ticket Autopilot）
├── AGENTS.md / IDEA.md               # 项目北极星 / 复用优先原则
├── src/ticket_autopilot/             # ★ 产品包 Ticket Autopilot
│   ├── engine/                       #   Engine 编排内核（可 import ticket_autopilot.engine）
│   │   └── handlers/close_ticket.py  #     唯一触碰 Plane 的节点（复用 reference）
│   ├── connectors/                   #   Connector 层（外部系统适配）
│   ├── cli.py schemas/ services/     #   产品 CLI / 规格 / 业务服务（骨架）
│   ├── reference/ticket-pipeline/    #   前身 PoC（orchestrator/plane_client/dagu-poc）
│   ├── workflows/                    #   YAML 工作流定义
│   └── runs/ sandbox/                #   运行期产物（gitignored，保留 .gitkeep）
├── tooling/
│   ├── start-prompt/                 # parked：提示词真源 + 评测（core/modules/platform/eval）
│   └── codex-notification-setup/     # parked：codex 基建配置
├── specs/  research/  logs/  tasks/  tests/
```

### 命名决策原由（避免后续踩坑）
- **Connector 而非 Handler**：`Handler` 指细粒度单步处理函数，且与引擎内部已有的 `engine/handlers/`（YAML `script` 节点的步骤处理器）撞名；Connector 语义精确（接口转换）、零冲突。代码已用此名（`adapters/` 已改名 `connectors/`）。
- **Engine 合并进产品包**：历史上曾存在独立的 `ticket-autopilot/`（前身 Vivarium Forge Flow / `vff`）与顶层产品骨架 `src/ticket_autopilot/` 撞名。决策将独立引擎收编为 `engine/`，消除"两个 Ticket Autopilot"的歧义——整个产品 = Engine + Connector + 业务服务。
- **遗留名已清除**：`vff` / `vivarium` / `forge_flow` / `forge-flow` / `Forge Flow` 已从代码与文档全部移除。
- **两个容易混淆的 `ticket-autopilot`**：`src/ticket_autopilot/` 是**源码包**；规格书/任务票里的 `.ticket-autopilot/` 是**运行期点文件夹**（worktree/run 目录），属规格定义、刻意保留，二者不是同一物。

## 开发

```bash
pip install -e .
ticket-controller --help
```

任务票见 `tasks/ticket-autopilot-v0.1-tasklist.md`。

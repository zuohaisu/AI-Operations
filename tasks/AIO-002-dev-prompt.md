# AIO-2 开发提示词（Development Prompt）

> 本文件是交给「开发 Agent」的独立执行提示词，自包含，开发 Agent 不需要本仓库之外的上下文。
> 任务来源：Plane 项目 **Ticket Autopilot / AIO**（workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）→ Issue **#2「定义并接通闭环工单工作流」**（issue id `aeb1339c-9b87-45a8-960a-a6d4c426beca`）。
> 风险等级：**R0**（文档 / 流程 / 模板，极低风险，**不写生产代码**）。
> 唯一真相来源：本提示词 + `AGENTS.md` + `IDEA.md` + 本仓库现有 Engine/Connector 代码。

---

## 0. [Goal check]（每段工作开头必须输出此行）

> [Goal check] This work advances **闭环定义（Closed-Loop Definition）** stage by delivering an authoritative, tool-supported workflow definition + a usable goal-drift template + an enforceable [Goal check] convention, grounded in the current Engine+Connector architecture.

若无法用一句话填完上面这行，先停下，不要动手。

---

## 1. 背景与目标（Goal）

仓库已经有了一份**能跑通**的闭环雏形：

- `src/ticket_autopilot/engine/engine.py` —— DAG + 重试循环的声明式解释器（forward 边定义 `needs`，loop 边实现 verify→execute 语义重试）。
- `src/ticket_autopilot/workflows/ticket-pipeline.yaml` —— 闭环定义：
  `plan`(llm) → `execute`(cli, `cwd=./sandbox`, `permission_mode=read-only`, `tools` 白名单) → `verify`(llm, `expect: json`, 输出 `accept`/`reject`) → `close`(script, `close_ticket`)。
  loop 边：`verify` 输出 `reject` → 回到 `execute`（`max_retries` 默认 5）；`accept` → `close`。
- `src/ticket_autopilot/engine/handlers/close_ticket.py` —— 唯一触碰 Plane 的节点（写评论 + 置 done），复用 `reference/ticket-pipeline/plane_client.py`。
- `src/ticket_autopilot/engine/tests/test_engine.py` —— 现有自测（重试循环、输入模板、cli 目录护栏、hermes 驱动），**全绿**。
- `connectors/`、`services/`、`schemas/` 目前是**空脚手架**（仅 `__init__.py`）；产品级 CLI `src/ticket_autopilot/cli.py` 是 **stub**。

**但**仓库目前缺一份把「宪章级原则」（AGENTS.md / IDEA.md）映射到「具体节点 / 脚本 / 命令」的**权威、可执行的闭环定义**。本票目标：

1. 让 `AGENTS.md` / `IDEA.md`（及其引用的闭环定义）成为闭环的**唯一定义来源**，且每个阶段都有**具体、有工具支撑、可实际执行**的步骤。
2. 固化 `logs/goal-drift.md` 的条目模板，使其**可直接机械填写**。
3. 把「每段工作开头先输出一行 `[Goal check] …`」落实为**可事后核验**的强制约定。

---

## 2. 范围边界（Scope Boundary）

### In scope（必须做）
1. **权威闭环定义文档**：在 `AGENTS.md`（首选，作为唯一真相入口）中新增一个具体的「Closed-Loop Workflow Definition」小节（或在 `docs/closed-loop-workflow.md` 写详版并从 `AGENTS.md` 用一行引用），把以下 7 个阶段逐一映射到**当前架构的真实实体**，并写明每阶段的：负责实体（Engine 节点 / Connector / 脚本）、使用工具 / 命令、如何执行、以及「证据门禁」是什么。

   | 阶段 | 当前负责实体（真实存在） | 证据门禁 |
   |---|---|---|
   | 工单接入与契约 | Connector（Plane 适配器；现为 `engine/handlers/close_ticket.py` 复用的 `reference/ticket-pipeline/plane_client.py`；目标形态 `connectors/plane.py`，见 AIO-8） | 结构化字段齐全 |
   | 计划 Plan | Engine `planner` 节点（driver: llm） | 产出 plan 文本 |
   | 执行/开发 Execute | Engine `executor` 节点（driver: cli，`cwd=./sandbox`，`permission_mode=read-only`，`tools` 白名单；或 hermes 变体 `workflows/ticket-pipeline-hermes.yaml`） | 目录沙箱 + 只读 + 工具白名单生效（已有 `SecurityError` 护栏） |
   | 确定性验证与独立 QA | Engine `verifier` 节点（driver: llm，`expect: json`，输出 `accept`/`reject`） | verdict=accept 才前进；**当前是 LLM verdict，Codex 独立 QA 升级见 AIO-7** |
   | 有界修复循环 | `verify`→`execute` 的 loop 边（`when: decision=='reject'`，`max_retries` 默认 5，变量 `vars.max_retries`） | 重试耗尽 → 停止（不假成功） |
   | Pull Request 与 CI 证据 | Connector（GitHub；**待 AIO-8 落地，本票只引用不实现**） | PR 存在 + CI 通过 |
   | 工单状态与结果 | Engine `closer` 节点（driver: script，entry: `close_ticket`，写评论 + 置 done） | Plane 状态已更新 |

   每个阶段引用的文件路径 / 节点 id / 命令必须**真实存在**，不得虚构。

2. **goal-drift 模板固化**：核对 `logs/goal-drift.md` 现有的 `## Entry template`（位于文件底部），确保它与 2026-07-22 真实条目结构完全一致且字段可机械填写；若缺项则补齐。不要另起一套模板，复用并打磨现有那一份。

3. **[Goal check] 强制约定 + 可核验方式**：在闭环定义文档中明确「每段工作开头必须先输出一行 `[Goal check] …`」，并给出一种**可事后核验**的执行/检查方式（例如：文档中列出检查清单；或提供一个轻量脚本/命令能扫描工作产物首行是否含 `[Goal check]`；或在 AGENTS.md 现有要求旁加一句可复核说明）。不强制接入 CI，但必须「人工或脚本可在事后核验」。

### Out of scope（严禁做）
- **不要新建平台 / 新编排框架**（复用现有 Engine，不要重写 `engine.py` / `drivers.py` 的运行逻辑）。
- **不要实现** GitHub / Linear Connector 代码（那是 AIO-8 / 后续票）。
- **不要实现 resume**（AGENTS.md / IDEA.md 明确排除）。
- **不要扩展**到 v0.2 能力（Webhook 触发、并行 Run、自动 merge、自动部署、自动迁移、自动选下一票）。
- **不要碰**生产代码、生产密钥、数据库迁移。
- **不要写**会把本票变成"实现闭环"的代码——本票是**定义与接线说明**，闭环已经由 Engine 实现。

---

## 3. 验收标准（Acceptance Criteria，逐条 Pass/Fail）

- **AC-1**：存在权威闭环定义（在 `AGENTS.md` 或 `docs/closed-loop-workflow.md`），覆盖全部 7 个阶段，每阶段含「负责实体 + 工具/命令 + 执行方式 + 证据门禁」，且引用的文件/节点 id 在仓库中**真实存在**（可 grep/Read 核验）。
- **AC-2**：文档把 `[Goal check]` 列为每段工作的强制第一步，并给出**可事后核验**的执行/检查方式（非空话）。
- **AC-3**：`logs/goal-drift.md` 含可直接使用的 Entry template，字段与 2026-07-22 真实条目一致（Intended outcome / Observed divergence / Evidence / Facts vs inference / Impact / Correction / Guard / Recovery milestone）。
- **AC-4**：文档显式声明本闭环**不**包含 v0.2 能力（no resume / no webhook / no parallel / no auto-merge），与 `AGENTS.md` / `IDEA.md` 一致。
- **AC-5**：文档与 `AGENTS.md` / `IDEA.md` 无矛盾，且 `AGENTS.md` 用一行引用该定义作为「闭环定义来源」。

---

## 4. 验证方式（Verification，确定性门禁）

- 现有测试不得被破坏（本票理想情况只动文档；若你被迫改动代码需保持绿）：
  ```bash
  python -m unittest discover -s src/ticket_autopilot/engine/tests
  ```
- 人工 / 脚本核验：
  - `grep -n "Goal check" <闭环定义文档>` 能命中强制约定段落。
  - 文档中引用的每个文件路径 / 节点 id 在仓库真实存在（用 grep / Read 核验，发现虚构引用即不合格）。
  - `logs/goal-drift.md` 的 Entry template 字段齐全、可被机械填充。

---

## 5. 依赖（Dependencies）

- 前置（建议先读其产出）：**AIO-1 复用优先能力审计**（`research/capability-audit.md`）。据此在文档中标注「哪些阶段已有工具闭合、哪些仍需 Connector/Engine 胶水」，收窄自定义范围。
- 参考（真实存在）：`src/ticket_autopilot/engine/*.py`、`workflows/ticket-pipeline.yaml`、`workflows/ticket-pipeline-hermes.yaml`、`engine/handlers/close_ticket.py`、`reference/ticket-pipeline/plane_client.py`、`logs/goal-drift.md`、`AGENTS.md`、`IDEA.md`。
- ⚠️ **不要**把 `tasks/ticket-autopilot-v0.1-tasklist.md`（T0–T19）当作架构依据——它描述的是**旧架构**（`ticket_controller` 包 + linear/github/claude/codex 适配器），与当前 Engine+Connector 架构不符，已过时。

---

## 6. Definition of Done

- [ ] 权威闭环定义已落地，且被 `AGENTS.md` 引用（或被 `AGENTS.md` 直接包含）
- [ ] 7 个阶段逐一映射到当前架构真实实体 + 证据门禁
- [ ] `[Goal check]` 强制约定 + 可核验方式就位
- [ ] `logs/goal-drift.md` 的 Entry template 可用
- [ ] 现有单元测试仍全绿
- [ ] 无 scope 蔓延（逐条对照 Out of scope）

---

## 7. 风险与回滚（Risk & Rollback）

- 风险：文档与现有代码 / 宪章表述不一致，反而制造新歧义。
- 回滚：文档类产物，`git revert` 即可；不影响运行代码。

---

## 8. 人工点位（Human touchpoints）

- **Trigger**：PM 将本票置 `In Progress` 即启动（唯一需要的人工启动动作）。
- **Gate**：PR review（本票产出为文档/模板，需人 review 才合并）。
- **Escalation**：3 次失败重跑后升级给 PM。

---

## 9. 硬性约束（来自 AGENTS.md / IDEA.md，违反即 BLOCKED）

- **复用优先**：能用现有 Engine / Connector / MCP 闭合的阶段，不新建代码。
- **只认证据不认自述**：文档化的步骤必须可被实际执行 / 核验，不得写「应该能做」。
- **不建新平台、不实现 resume、不自动 merge、不碰生产**。
- **凭证**从环境变量 / Keychain 读取，不落地明文（本票不涉及，但提及即遵守）。
- 任一确定性失败只标 `BLOCKED`，绝不标成功。

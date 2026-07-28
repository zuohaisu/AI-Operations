# AIO-3 开发提示词（Developer Prompt）

> 由 PM agent 生成，交给**开发 agent** 执行。开发 agent 开始前必须先读 `AGENTS.md` 与 `IDEA.md`，并在工作开头输出一行 `[Goal check]`。
> 这是一份 agent-ready 工单：移入 In Progress 即可自主执行，无需中途人工决策。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）
- 工单：AIO-3「项目脚手架骨架」
- Plane issue id：`c76822b0-223d-4dd9-bf0c-a323097eab42`
- 优先级：medium｜标签：scaffolding, tooling｜风险等级：**R0**（纯文档/脚手架，无代码风险）
- ⚠️ 位置说明：AIO 任务在 **Plane**，不在 Linear（Linear 无 AIO 项目）。本提示词即任务说明来源。

## [Goal check]
本工作推进「脚手架（Scaffolding）」阶段，证据 = 交付 5 个脚手架产物（CONTRIBUTING / PR 模板 / memory 布局说明 / 可复用 ticket 模板 / 自描述 README），使未来 AI 驱动项目可快速启动。

## 背景与项目现状（先对齐，避免重复造轮子）
仓库**当前已具备**：
- 目录结构：`specs/`（含 `agent-ready-ticket-template.md`）、`research/`、`tooling/`、`logs/`、`src/`、`tests/`、`tasks/` 均已存在。
- 闭环定义：`AGENTS.md`、`IDEA.md` 已定义 ticket 闭环与 `[Goal check]` 规则（即 AIO-2 的产出）。
- 持久上下文：`.workbuddy/memory/` 已存在 `MEMORY.md` 与每日日志（`2026-07-22.md` 等）。
- 根 `README.md` 已存在（内容待充实）。
- 模板：`specs/agent-ready-ticket-template.md` 已存在（含 9 字段：Title/Goal/Scope/AC/Verification/Dependencies/DoD/Risk/Human）。

**当前缺口（本任务要补齐）：**
- ❌ 没有 `CONTRIBUTING.md`（贡献 / PR 流程未成文）
- ❌ 没有 `.github/PULL_REQUEST_TEMPLATE.md`
- ❌ `.workbuddy/memory/` 缺少布局说明文档
- ⚠️ `agent-ready-ticket-template.md` 存在，但未明确“对齐 senior-project-manager 格式”的**空白可填版**与 **spec→issue 操作流程**
- ⚠️ 根 `README.md` 未描述目录结构与上述脚手架资产

## 目标（Goal）
把本项目所需的仓库脚手架固化成可复用资产，使未来任何 AI 驱动项目都能快速启动；**不新建平台，只做文档与模板**。

## 范围边界
**In scope（交付物）：**
1. `CONTRIBUTING.md`：贡献流程 + PR 流程（分支命名、PR 模板用法、review/merge 人工闸、agent 建 PR 约定、闭环状态映射）。
2. `.github/PULL_REQUEST_TEMPLATE.md`：含 关联工单(Plane key)、Goal、Scope(in/out)、AC 勾选清单、验证证据、风险/回滚。
3. `.workbuddy/memory/README.md`：持久上下文布局说明（MEMORY.md 长期记忆 + `YYYY-MM-DD.md` 每日日志；何时写、写什么、不写什么）。
4. 固化 `specs/agent-ready-ticket-template.md`：明确对齐 senior-project-manager 9 字段格式；新增「空白可填模板」与「spec → Plane issue 操作流程」；从 CONTRIBUTING 与 README 交叉引用。
5. 更新根 `README.md`：描述目录结构、指向 `AGENTS.md`/`IDEA.md`/`CONTRIBUTING.md`/`specs/agent-ready-ticket-template.md`/`.workbuddy/memory/README.md`，使脚手架自描述。

**Out of scope（禁止）：**
- 不新建任何平台 / 服务 / CLI / 自动化脚本（D4 只允许“文档化”，不允许写代码）。
- 不改动 `src/` 下的产品代码。
- 不引入新的依赖或构建系统。
- 不重写 `AGENTS.md`/`IDEA.md` 的闭环定义（只引用，不复制）。

## 验收标准（Acceptance Criteria）
- **AC-1**：`CONTRIBUTING.md` 存在，且覆盖 ≥5 项：分支命名约定、PR 模板使用方式、review/merge 人工闸、agent 建 PR 约定、闭环状态映射（In Progress / In Review / Blocked）。
- **AC-2**：`.github/PULL_REQUEST_TEMPLATE.md` 存在，且包含 ≥6 区块：关联工单、Goal、Scope(in/out)、AC 勾选清单、验证证据、风险/回滚。
- **AC-3**：`.workbuddy/memory/README.md` 存在，说明 MEMORY.md 与每日日志的用途、写入时机、以及“不写什么”。
- **AC-4**：`specs/agent-ready-ticket-template.md` 明确标注对齐 senior-project-manager 9 字段，并包含「空白可填模板」+「spec → Plane issue 操作流程」两节。
- **AC-5**：根 `README.md` 描述目录结构，并链接到上述 4 个资产（CONTRIBUTING / PR 模板 / memory README / ticket 模板）。
- **AC-6**：所有新增/修改的 `.md` 文件内部交叉链接无失效（指向的本地路径真实存在）。

## 验证方式（Verification — 确定性闸）
- 类型：**inspection**（文档检查，非跑测试）
- 开发 agent 自查命令：
  ```bash
  for f in CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md \
           .workbuddy/memory/README.md specs/agent-ready-ticket-template.md README.md; do
    test -f "$f" && echo "OK  $f" || echo "MISSING  $f"
  done
  ```
- 通过 = AC-1~AC-6 全部满足，且文档内部无失效链接。
- 失败 = 任一条 AC 不满足 → 进入有界修复（最多 2 轮）。

## 依赖（Dependencies）
- 依赖 AIO-2「定义并接通闭环工单工作流」：其产出 `AGENTS.md`/`IDEA.md` 已存在，视为已满足；本任务只引用，不修改。
- 无阻塞环境变量 / 外部服务依赖。

## 完成定义（Definition of Done）
- [ ] AC-1 ~ AC-6 全部满足
- [ ] 文档自查无失效链接
- [ ] 不触碰 `src/` 产品代码、不新建平台
- [ ] 产出 Developer Summary（人读，不参与状态判断）
- [ ] 由 Controller / 人工创建 PR（**开发 agent 不自行建 PR**）

## 风险与回滚（Risk & rollback）
- 风险：新文档与现有 `README.md`/`AGENTS.md` 内容重复或冲突 → 以**引用代替复制**，保持单一信息源。
- 回滚：纯文档改动，`git revert` 即可；无数据/生产影响。

## 人工点位（Human touchpoints）
- **Trigger**：PM 将 AIO-3 置 In Progress（本提示词即启动信号）。
- **Gate**：PR 由人工 review 后合并（脚手架文档也需人确认风格/口径）。
- **Escalation**：若对“senior-project-manager 格式”口径有歧义，标记 `BLOCKED_NEEDS_HUMAN`，不要猜。

## 开发 agent 执行指引（步骤）
1. 读 `AGENTS.md`、`IDEA.md`、`specs/agent-ready-ticket-template.md`、当前 `README.md`、`.workbuddy/memory/MEMORY.md`。
2. 列出现状缺口（见上文），确认无遗漏。
3. 按交付物 **1 → 5** 顺序产出/修改文件，保持**引用而非复制**单一信息源。
4. 每产出一个文件，自查对应 AC 条目。
5. 运行上面的验证命令自查。
6. Commit（message 含 `AIO-3`），输出 Developer Summary，**不要自行建 PR**。

## 硬性约束（来自 AGENTS.md）
- 复用优先、不新建平台：本任务本质是“文档化已有脚手架”，禁止引入新工具。
- 证据优先：不以“我觉得写完了”自证，以文件存在 + 内容满足 AC 为证。
- 不扩大 Scope：只做 In scope 五项；其余一律 Out。
- 不修改产品代码（`src/`）、不触碰生产。

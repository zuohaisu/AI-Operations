# AIO-4 开发提示词（Development Prompt）

> 本文件是交给「开发 Agent」的独立执行提示词，自包含，开发 Agent 不需要本仓库之外的上下文。
> 任务来源：Plane 项目 **Ticket Autopilot / AIO**（workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）→ Issue **#4「标准化 spec→issue 任务模板」**（issue id `6ce345cd-ff51-4160-8e81-d2a8d4443960`）。
> 风险等级：**R0**（文档 / 流程 / 模板 + 轻量工具，极低风险，**不写生产代码**）。
> 唯一真相来源：本提示词 + `specs/agent-ready-ticket-template.md` + `docs/closed-loop-workflow.md` + `AGENTS.md` + `IDEA.md` + 本仓库现有代码。

---

## 0. [Goal check]（每段工作开头必须输出此行）

> [Goal check] This work advances **Ticket intake and contract** stage by turning the existing agent-ready ticket template into a reusable, automatable spec→issue process/skill that produces zero-scope-creep Plane issues (or issue groups) for any future spec.

若无法用一句话填完上面这行，先停下，不要动手。

---

## 1. 背景与目标（Goal）

仓库**已经**有一份成形的工单模板：

- `specs/agent-ready-ticket-template.md` —— 9 字段（Title / Goal / Scope boundary / Acceptance criteria / Verification / Dependencies / Definition of Done / Risk & rollback / Human touchpoints）+ **空白可填模板** + **「Spec → Plane issue 操作流程」小节（第 113–120 行）** + 一个 worked example。它已对齐 senior-project-manager 票格式，且被 `docs/closed-loop-workflow.md` 引用为「工单契约」来源。
- `docs/closed-loop-workflow.md` —— 闭环权威定义，第 1 阶段「Ticket intake and contract」明确引用该模板作为结构化工单字段来源。
- 9 个种子 Plane 工单（#1–#9）已由 REST API 导入（gotchas 见 `.workbuddy/memory/2026-07-27.md`），验证了「spec/想法 → Plane work-item」这条路本身可行。

**但**目前「spec → issue」仍是**人工流程**：模板有了，却没有一个**可复用、可机械校验、可重复执行**的机制去把「任意一份 spec」稳定地变成「带清晰验收标准、零范围蔓延的 Plane 工单（或工单组）」。本票目标（字面）：

> 把 spec→issue 流程固化为可复用的模板/流程，使未来任何 spec 都能变成带清晰验收标准、零范围蔓延的 Plane 工单（或工单组）。**沉淀为 skill 或文档以便复用。**

即：本票**不是从零写模板**（模板已存在），而是把「已有模板 + 导入经验」**固化成可复用机制**（首选 **skill**，其次文档 + 轻量脚本），并保证「零范围蔓延」被**强制**（而非靠人自觉）。

---

## 2. 范围边界（Scope Boundary）

### In scope（必须做）
1. **审计并锁定模板为唯一标准**：读 `specs/agent-ready-ticket-template.md`，确认它已含 9 字段 + 空白可填块 + Spec→Plane 流程 + worked example。在现有基础上**补齐/收紧**（不重写）：
   - 显式写出「**何时把一份 spec 拆成工单组**」的判定规则（单可交付单元 vs 多单元；依赖关系如何拆）。
   - 增加一格「**防范围蔓延核对清单**」（硬性）：Out-of-scope 必填且非空；Acceptance criteria 必须可测（Given/When/Then 或 pass/fail）；Verification 必须给出可机械执行的命令/检查（machine-checkable where possible）。
   - 明确「**未满 9 字段 / 缺 Verification 或 Scope boundary 的 spec 不得进入 In Progress**」的强制门禁（模板已有类似表述，请强化为可执行规则）。
2. **交付可复用机制（二选一，首选 skill）**：
   - **首选**：在仓库内创建 **project-level skill** `spec-to-plane-issue`（路径 `AI-Operations/.workbuddy/skills/spec-to-plane-issue/SKILL.md`，遵循 WorkBuddy SKILL.md 规范），让「给一份 spec → 产出合规 Plane 工单/工单组」可被一键调用。
   - **次选**：若不做 skill，则交付 `tooling/spec_to_issue.py` + 文档，功能等价。
   - 该机制必须：
     a. 吃一份 spec（文件路径或文本），输出 **1..N** 个符合模板 9 字段的工单草稿（markdown 或结构化）。
     b. **内建防范围蔓延校验**：缺 Scope boundary / AC 不可测 / Verification 不可执行 → 显式报错或标红，不产出「半截工单」。
     c. **编码 Plane REST gotchas**（来自 `.workbuddy/memory/2026-07-27.md`，必须硬编码进机制，别让调用者再踩）：
        - 建 work-item：`POST /projects/{pid}/work-items/`，仅 `name`/`description_html`/`priority`/`assignees` 生效；`state_id`/`label_ids`/`cycle_id` 在 body 里**被静默忽略**。
        - 设状态 + 标签：`PATCH /work-items/{id}/`，字段名用 `state`（非 `state_id`）、`labels`（非 `label_ids`）。
        - 加 cycle：`POST /cycles/{cid}/cycle-issues/`，body `{"issues":["<work_item_id>"]}`（非 `issue_ids`/`work_item_ids`）。
        - 认证头 `X-Api-Key`；base `https://api.plane.so/api/v1`（或读 `PLANE_*` 环境变量）。
     d. 提供 **dry-run / preview 模式**（默认）：只产出工单 markdown，**不触网、不写真实 Plane**。真实创建必须显式 `--apply` 且经人工确认（见 §8 Gate）。
3. **确定性自检（必做）**：机制必须能被机械校验。提供内置示例 spec（`tests/fixtures/sample-spec.md` 或机制内联），运行 `dry-run` 后断言产出满足 9 字段 + 防范围蔓延规则。给出可复现命令并**全绿**。

### Out of scope（严禁做）
- **不重写 / 不另起一套模板**：必须建立在现有 `specs/agent-ready-ticket-template.md` 之上，禁止新建 `ticket_controller` 式旧架构（见 `tasks/ticket-autopilot-v0.1-tasklist.md`，已过时，**禁止**作依据）。
- **不碰生产代码**：不要改 `src/ticket_autopilot/engine/*`、`connectors/`、`reference/ticket-pipeline/plane_client.py`、任何运行时逻辑。本票是 docs + tooling。
- **不重建 Plane client / Engine**：复用现有 `plane_client.py` 思路或 REST gotchas 即可，不要写新编排。
- **不实现 CONTRIBUTING.md / PULL_REQUEST_TEMPLATE.md**：模板里 forward-reference 了 `../CONTRIBUTING.md` 与 `../.github/PULL_REQUEST_TEMPLATE.md`，它们归 **AIO-3（项目脚手架骨架）**；本票可保留引用，但**不得实现**它们。
- **不自动创建 9 个种子工单**（已存在）；机制只面向「未来新 spec」。
- **不在未经 `--apply` + 人工确认时写入真实 Plane**；禁止在测试/自检里触网。

---

## 3. 验收标准（Acceptance Criteria，逐条 Pass/Fail）

- **AC-1**：`specs/agent-ready-ticket-template.md` 是**唯一权威模板**，含 9 字段 + 空白可填块 + Spec→Plane 流程 + worked example；且新增了「拆分工单组规则」+「防范围蔓延核对清单」+「未满字段不得 In Progress 的强制门禁」（读文档核验，grep 命中关键小节）。
- **AC-2**：可复用机制存在（`AI-Operations/.workbuddy/skills/spec-to-plane-issue/SKILL.md` 或 `tooling/spec_to_issue.py`），能对任意 spec 产出 1..N 个合规工单草稿，且**内建防范围蔓延校验**（缺关键字段/不可测 AC/不可执行 Verification 时显式失败）。
- **AC-3**：机制**编码了 Plane REST gotchas**（state/label 用 PATCH `state`/`labels`、cycle 用 `POST /cycles/{cid}/cycle-issues/` `{"issues":[...]}`、建 work-item 仅生效 name/desc/priority/assignees）；并有 dry-run/preview 默认不触网。
- **AC-4**：确定性自检通过——对内置示例 spec 跑 `dry-run`，断言产出满足 9 字段 + 防范围蔓延规则；命令可复现且**全绿**。自检**不依赖网络/真实 Plane**。
- **AC-5**：无 scope 越界——未改 Engine/Connector/plane_client；未重建平台；未实现 CONTRIBUTING/PR 模板（仅 forward-reference）；未触网写入真实 Plane（除非显式 `--apply` + 人工确认，且本验收不要求）。
- **AC-6（可选 / 非阻塞）**：演示——在 `--apply` + 人工确认下，用机制在 AIO 项目里真实创建 1 个标记为 `DRAFT` 的示例工单，证明端到端可用。未做不判 FAIL。

---

## 4. 验证方式（Verification，确定性门禁）

- 文档/模板类改动若涉及代码引用，先确保既有测试不破：
  ```bash
  PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -v   # 或 python -m unittest discover -s src/ticket_autopilot/engine/tests -v
  ```
- **主门禁（机制自检，必须全绿）**：
  ```bash
  # skill 形态：
  #   在 WorkBuddy 中调用 spec-to-plane-issue 对内置示例 spec 跑 dry-run，
  #   机制自身断言产出满足 9 字段 + 防范围蔓延；退出码 0。
  # 脚本形态：
  python tooling/spec_to_issue.py --dry-run --spec tests/fixtures/sample-spec.md --assert
  echo "EXIT=$?"   # 期望 0
  ```
- 人工 / 脚本核验：
  - `grep -n "Spec → Plane\|防范围蔓延\|拆.*工单组" specs/agent-ready-ticket-template.md` 命中新增小节。
  - dry-run 输出可用 Read 打开，肉眼确认 9 字段齐全、Out-of-scope 非空、AC 为 pass/fail、Verification 有具体命令。

---

## 5. 依赖（Dependencies）

- 前置（建议先读其产出，已 done）：
  - **AIO-1 复用优先能力审计**（`research/capability-audit.md`）——确认 Plane/Linear/GitHub 现有能力，本机制复用 REST gotchas 而非新建。
  - **AIO-2 闭环定义**（`docs/closed-loop-workflow.md` + `AGENTS.md`/`IDEA.md`）——本模板即其「Ticket intake」阶段的契约来源。
- 参考（真实存在）：`specs/agent-ready-ticket-template.md`、`docs/closed-loop-workflow.md`、`reference/ticket-pipeline/plane_client.py`（REST 思路）、`.workbuddy/memory/2026-07-27.md`（Plane gotchas 原文）。
- 关联但**不实现**：**AIO-3 项目脚手架骨架**（拥有 CONTRIBUTING.md / PR 模板，被本模板 forward-reference）。
- ⚠️ **禁止**把 `tasks/ticket-autopilot-v0.1-tasklist.md`（旧 `ticket_controller` 架构）当作模板/架构依据。

---

## 6. Definition of Done

- [ ] `specs/agent-ready-ticket-template.md` 收紧为唯一标准（含拆组规则 + 防蔓延清单 + 强制门禁）
- [ ] 可复用机制（`skill` 或 `tooling` 脚本）落地，内建防范围蔓延校验 + Plane gotchas + dry-run 默认不触网
- [ ] 确定性自检全绿（对示例 spec，断言 9 字段 + 防蔓延，不依赖网络）
- [ ] 既有单测仍全绿（若被动过）
- [ ] 无 scope 越界（逐条对照 Out of scope）
- [ ] 复用优先：未新建平台 / 未重建 plane client / 未碰 Engine

---

## 7. 风险与回滚（Risk & Rollback）

- 风险：机制过度设计（写新编排/新 client）→ 必须回落到「docs + 轻量 skill/脚本」。
- 风险：dry-run 之外误触真实 Plane → 机制必须默认 preview，真实写入仅 `--apply` + 人工确认。
- 回滚：docs/tooling 类产物，`git revert` 即可；不影响运行代码。

---

## 8. 人工点位（Human touchpoints）

- **Trigger**：PM 将本票置 `In Progress` 即启动（唯一需要的人工启动动作）。
- **Gate**：PR review（产出为模板 + 机制，需人 review 才合并）。
- **Escalation**：3 次失败重跑后升级给 PM。
- 真实写入 Plane（AC-6）需 PM 显式确认后才 `--apply`。

---

## 9. 硬性约束（来自 AGENTS.md / IDEA.md，违反即 BLOCKED）

- **复用优先**：模板已存在 → 建立在它之上；gotchas 已记录 → 编码进去；不新建。
- **只认证据不认自述**：机制的「零范围蔓延」必须有可机械执行的校验 + 自检全绿，不得写「应该能拦住」。
- **不建新平台、不碰生产**：不写 Engine/Connector/plane_client；不实现 AIO-3 的 CONTRIBUTING/PR 模板。
- **凭证**从环境变量（`PLANE_*`）读取，不落地明文。
- **绝不触网自检**：所有验证在 dry-run 下完成；真实 Plane 写入仅限 `--apply` + 人工确认。
- 任一确定性失败只标 `BLOCKED`，绝不标成功。

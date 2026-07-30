# Ticket Autopilot — 产品需求文档（PRD）

**版本：** v1.0（产品级 PRD）
**状态：** Historical design baseline — current Phase 1 implementation is documented in `README.md` and `docs/closed-loop-workflow.md`
**日期：** 2026-07-29
**Owner：** Haisu Zuo（产品 + 唯一人类干系人）
**适用项目：** `AI-Operations` 仓库内的 `src/ticket_autopilot/` 包（未来开源为独立 repo）

> **[Goal check]** 本 PRD 推进闭环阶段「产品定义」——把已落地的 9 张票（AIO-1~9）沉淀为一份可被干系人对齐、可被执行 agent 复用的权威需求文档，并显式标注与旧 `v0.1 Specification` 的架构偏离。

---

## 0. 与 `v0.1 Specification.md` 的关系（必读偏离声明）

`specs/Ticket Autopilot v0.1 Specification.md`（2026-07-20）是**早期 fallback 设计**，其描述的架构**已不再代表当前产品**：

| 维度 | v0.1 规范（已偏离） | 当前实际产品（本 PRD 依据） |
| --- | --- | --- |
| 工单源 | Linear Issue | **Plane**（可插拔，未来接 Linear/GitHub） |
| 包名 | `ticket_controller` | **`ticket_autopilot`**（Engine + Connector + Drivers） |
| 开发 Agent | Claude Code 单点 | Execute ×2 互为备份：Claude Code + 「pi」 |
| 独立 QA | Codex 单点 | Verify ×2 互为备份：QoderWake CLI + Codex |
| Plan 角色 | 无显式 | Codex CLI（本机无 WorkBuddy CLI 二进制） |
| 编排内核 | 单一 Controller 状态机 | **声明式 Engine**：YAML→DAG，Plan→Execute→Verify→Close，Verify 拒绝时自动重跑 Execute（默认 `max_retries=5`） |
| 沙箱/护栏 | 文档描述，未强制 | **AIO-9 落地**：cwd 沙箱 + 只读强制 + 工具白名单，spawn 前拦截 |
| 连接器 | Linear/GitHub/Claude/Codex 适配器 | **当前落地**：`connectors/plane.py`（取票/关单）、`connectors/github.py`（建草稿 PR；仅凭 repo-owner 显式授权 merge）、`connectors/qa.py`（只读 verdict 门禁） |

本 PRD 保留 2026-07-29 的产品决策背景；它不再是 Phase 1 的实施状态或操作说明。AIO-17 至 AIO-20 已实现 localhost Web 控制台、Plane intake、Prompt preparation、五轮 Developer/QA loop、local Commit 和 Timeline。实际边界、已知限制和验证命令以 `README.md` 与 `docs/closed-loop-workflow.md` 为准；本文件中任何与它们冲突的“当前实际”表述均应按历史设计阅读。

---

## 1. 问题陈述（Problem Statement）

### 1.1 现状痛点
把一张结构化工单变成「代码改完、测试通过、独立 QA 通过、等待人审」的 Pull Request，今天需要人类手工串联一连串高摩擦操作：

- 从工单系统读需求 → 手写开发 Prompt → 启动开发 Agent → 等结果 → 收集报告
- 手写 QA Prompt → 启动 QA Agent → 把 Finding 复制回开发 Agent → 再启动 QA
- 更新工单状态 → 创建 / 检查 PR

### 1.2 谁在承受、频率如何
唯一核心用户是 **Haisu（独立开发者 / 个人项目 owner）**，每天可能发起 1–5 张低风险工单。痛点随工单量线性放大。

### 1.3 不解决的代价
- **速度**：每张工单的「人肉编排」消耗 10–30 分钟纯机械操作，挤压真正的开发时间。
- **质量风险（伪成功）**：人类容易**信任 Agent 的自我报告**（"我改完了 / 测试都过了"），缺少确定性证据闸门，劣质代码可能直接进入 PR。
- **范围蔓延**：手工流程中 Agent 容易越界改无关代码、碰 main、碰生产。
- **不可复盘**：过程证据散落聊天记录，无法审计「为什么这张票没过 QA」。

### 1.4 证据基础
- 个人开发日常观察（高频手工 Prompt 复制）；
- `AIO-5` 垂直切片实测：即使刻意选低风险 CI 工单，闭环仍卡在「无独立 QA driver / 无授权 Plane MCP」的能力缺口上，印证了**编排 + 证据闸门 + 护栏**才是真问题，而非「再写几个 Prompt」。

---

## 2. 产品定位与核心价值

**Ticket Autopilot 是一个运行在本地的、复用优先的轻量控制器**：它把一张结构化工单，经过「计划 → 执行 → 确定性验证 → 独立 QA → 有界修复 → 关单/建 PR」的闭环，转化为一张**已验证、经独立 QA、等待人工 Review 的 GitHub PR**。

它**不是**通用多 Agent 平台，而是**一个被严格约束的闭环实验**：在「不复制 Prompt、不牺牲证据质量、不突破安全边界」的前提下，验证结构化工单能否被自动变成可信 PR。

### 两个承重契约（产品灵魂）
- **`ticket-spec.json`（输入契约）**：工单必须能被结构化（Goal / Scope / Out-of-scope / AC / 验证命令 / Risk Tier / 约束）。
- **`qa-verdict.json`（输出契约）**：QA 产出必须过 Schema 校验，且 `verdict=PASS` 才能放行——**证据而非声明**决定状态推进。

---

## 3. 目标（Goals）

> 目标用「成功长什么样」度量，而非「做了什么」。

**用户目标**
- G1：发起一张低风险工单后，人类**零 Prompt 复制**、零手工串联即可拿到 review-ready PR 或明确的 Blocked 结论。
- G2：任何「完成」状态都**附带确定性证据**（Commit / Diff / 测试 Exit Code / QA Verdict），杜绝伪成功。
- G3：Agent 在沙箱内运行，**永远不能**直推 main、不能碰生产、不能自我授权 merge；Repo Owner 保留显式 push/PR/override/merge 决策权。

**业务/个人目标**
- G4：工单→review-ready PR 的**中位耗时**较手工流程下降 ≥ 50%。
- G5：≥ 60% 的符合条件低风险工单在 GA 后一个季度内走通自动闭环。
- G6：False PASS = 0；越权事件 = 0；工程证据保留率 = 100%。

---

## 4. 非目标（Non-Goals）

| # | 非目标 | 为什么 out-of-scope |
| --- | --- | --- |
| NG1 | 通用多用户 Web 平台 / 远程控制台 | Phase 1 已实现 localhost-only 单人 Web 控制台；远程访问、鉴权、多用户与通知仍不在范围。 |
| NG2 | Agent 自主 Merge / 自动生产部署 / 自动迁移 | 安全边界约束自动化主体；Repo Owner 的显式 merge 授权不是自动 Merge。 |
| NG3 | 多工单队列 / 并行 Run / 远程持久服务 | 当前是个人单工单、localhost-only Run；复杂度与收益不匹配。 |
| NG4 | Run Resume（断点续跑） | 采用「一次性可丢弃 Run」模型：崩溃即 Abort→Cleanup→新建 Run 重头跑，接受额外 Token 成本换实现简单。 |
| NG5 | 工单自动选型 / 自动写需求 | 工单由人类在 Plane 中创建与指派，Autopilot 不生产需求。 |
| NG6 | 新建平台/框架/引擎功能 | 复用优先：先用 Plane/GitHub Actions/Agent CLI/MCP 的现成能力，只在被证实的缺口上写最小胶水。 |

---

## 5. 角色与用户故事

### 5.1 角色
- **PM（人类，Haisu）**：在 Plane 写结构化工单、指派、最终决定 merge/Done。
- **Plan Agent（Codex CLI）**：读工单 → 产出实现方案。
- **Execute Agent ×2（Claude Code + 「pi」）**：在沙箱内实现代码与测试、Commit。
- **Verify Agent ×2（QoderWake CLI + Codex）**：只读审查 Diff / AC / 测试充分性 → 输出 `qa-verdict.json`。
- **Repo Owner / 人类审查者**：Review PR；可显式接受视觉门禁、记录 override、授权 feature-branch push 或 Merge。
- **Engine（控制器内核）**：驱动 DAG、执行重试循环、落快照、调用 Connector。

### 5.2 用户故事（按优先级）
1. **作为 PM**，我希望把一张结构化 Plane 工单交给 Autopilot，以便零手工串联地拿到一张待审 PR。（P0）
2. **作为 PM**，我希望任何「完成」状态都附带可核验证据，以便我不信任 Agent 自我报告也能放心 Review。（P0）
3. **作为 Execute Agent**，我希望只在隔离沙箱内拿到明确的工单契约与修复清单，以便我不越界、不碰 main。（P0）
4. **作为 Verify Agent**，我希望只读拿到原始契约 + 当前 Diff + 测试证据，以便独立给出 PASS/FAIL 判定。（P0）
5. **作为 Repo Owner**，我希望 Agent 永不自行 Merge，但我可以显式创建/推进 PR、接受或 override 门禁并决定 Merge 节奏，以便最终控制权真正留在我手中。（P0）
6. **作为 PM**，我希望 QA 拒绝时只把原 Finding 交回 Execute 做窄修复，以便不扩大 Scope。（P1）
7. **作为 PM**，我希望 Run 崩溃后可一键 Cleanup 且**不删除**已合并代码与生产数据，以便安全重试。（P1）
8. **作为 PM**，我希望看板能只读展示每次 Run 的状态/证据，以便非技术干系人也能感知交付进度。（P2）

---

## 6. 闭环工作流（Closed-Loop Workflow）

```text
Plane Ticket
   ↓  (人类指派 / 手动启动)
Engine: 读取并校验 ticket-spec.json
   ↓  结构不合规 → BLOCKED_REQUIREMENTS（不调用任何 Agent）
Plan      → 产出实现方案（Codex CLI）
Execute   → 沙箱内实现 + 测试 + Commit（Claude Code / pi）
Verify    → 只读 QA → qa-verdict.json
   ├── PASS  → Close：建草稿 PR（github connector）+ Plane 置 In Review
   ├── FAIL  → 把原 Finding 交回 Execute（窄修复），重跑 Execute→Verify
   └── BLOCKED → 置 Plane Blocked，等人类决策
   （Verify 拒绝时自动重跑，默认 max_retries=5）
```

**关键纪律**
- **确定性动作不让 LLM 做**：建 Worktree/Branch、跑测试、读 Exit Code、建 PR、校验 JSON Schema、统计重试次数，全部由 Engine 确定性完成。
- **证据优于声明**：只有 Git Commit / 非空 Diff / 测试 Exit Code=0 / QA Verdict 过 Schema 且 =PASS，才推进。
- **无伪成功**：不确定/输出畸形/证据缺失/QA 超时 → 一律 BLOCKED，绝不标记成功。

---

## 7. 系统架构

```text
Plane ──(connector/plane: 取票/关单)──┐
                                       ↓
Local Engine (声明式 YAML→DAG + 重试循环 + 快照)
   ├── drivers: llm / cli / hermes / script / mock
   ├── guardrails: cwd 沙箱 + 只读强制 + 工具白名单（spawn 前拦截）
   └── handlers/close_ticket: 唯一触碰 Plane 的节点
                                       ↓
GitHub ──(connector/github: 草稿 PR + repo-owner 显式授权 merge)──┐
QA ──────(connector/qa: 只读 → qa-verdict.json → 确定性校验门禁)─┘
```

| 层 | 职责 | 当前状态 |
| --- | --- | --- |
| **Engine** (`engine/engine.py`) | YAML→DAG、Verify 拒绝重试、Run 快照 | AIO-2 已落地，mock 跑通 |
| **Drivers** (`engine/drivers.py`) | llm/cli/hermes/script/mock 五类执行器 | AIO-6 已落地 |
| **Guardrails** (`engine/guardrails.py`) | cwd 沙箱 + 只读 + 白名单 | AIO-9 已落地 |
| **Connector: Plane** (`connectors/plane.py`) | 取票 / 建 workflow / 关单置 Done | AIO-8 已落地 |
| **Connector: GitHub** (`connectors/github.py`) | 建草稿 PR；凭 repo-owner 单次授权 merge（head 必为独立分支，永不 push main） | 已落地 actor-aware authorization |
| **Delivery Policy** (`services/delivery_policy.py`) | 区分 pending warning、Diff split、owner override、merge authorization 与真实技术阻塞 | 已落地 |
| **Connector: QA** (`connectors/qa.py` + `schemas/qa-verdict.schema.json`) | 只读 QA → 结构化 verdict → 确定性门禁 | AIO-7 已落地 |

> **目录真相**：产品代码在 `src/ticket_autopilot/`；旧 `specs/Ticket Autopilot v0.1 Specification.md` 与 `tasks/ticket-autopilot-v0.1-tasklist.md`（T0–T19，描述旧 `ticket_controller` 包）**已 STALE，勿作架构依据**。

---

## 8. 关键契约

### 8.1 `ticket-spec.json`（输入）
必填：Goal / Scope / Out-of-scope / Risk Tier（仅 R0/R1 可自动）/ Acceptance Criteria（每条带 `verification`：automated / query / inspection；`manual` 类型 → BLOCKED_REQUIREMENTS）/ Required Checks / Constraints（`max_fix_attempts`、`allow_main_push=false` 等）。
Engine **只做结构校验，不用 LLM 判断工单「写得好不好」**。

### 8.2 `qa-verdict.json`（输出）
必过 JSON Schema 校验。字段含 `verdict`（PASS/FAIL/BLOCKED）、逐条 AC 状态 + 证据、Findings（severity/type/required_fix）、`recommended_next_state`。`verdict=PASS` 是唯一放行条件。

---

## 9. 护栏与安全边界

- **Git 保护**：Agent 不得直推 main、不得自行 Merge；Controller 只在 repo-owner 对具体 action 提供 actor/time/reason 后 push feature branch 或 merge。QA/视觉 pending 可建 Draft PR，但不得伪装为 PASS。
- **沙箱**：所有 CLI 执行限定在 cwd 沙箱内，强制只读，工具白名单（AIO-9）。
- **生产边界**：禁止 SSH 生产、读生产库、改生产数据、读生产 Secret、自动部署、不可逆迁移。
- **凭证**：从环境变量 / OS Keychain / `gh` / Plane API Key 读取，**绝不写入配置文件或仓库**。

---

## 10. 需求（Requirements）

### P0 — Must-Have（缺一则产品不成立）
- **R1 工单契约校验**：结构不合规的工单在调用任何 Agent 前被拒（AC：缺 Goal/AC/verification、Risk≠R0/R1、manual 验证 → BLOCKED_REQUIREMENTS）。
- **R2 声明式 Engine 闭环**：YAML→DAG，驱动 Plan→Execute→Verify→Close；Verify 拒绝时自动重跑 Execute（AC：mock 跑通 plan→execute→verify(拒)→execute→verify(接受)→close）。
- **R3 确定性验证**：建 Run/Worktree/Branch、跑 `required_checks`、读 Exit Code、校验 Commit/非空 Diff，全部由 Engine 完成，不信任 Agent 报告（AC：Developer 声称完成但无 Commit → BLOCKED_ENVIRONMENT，不建 PR）。
- **R4 只读独立 QA 证据**：QA 只产出 `qa-verdict.json`；畸形输出不得冒充 PASS。`QA_PENDING`/视觉 pending 可建 Draft PR，只有 PASS 或 repo-owner 的显式 override 才能越过质量 gate，且 override 不改写原 verdict。
- **R5 Actor-aware Git 交付**：Connector 建 Draft PR（head 独立分支）；feature-branch push 与 merge 分别需要 repo-owner 单次授权。Agent 自授权、main push 和无审计 merge 次数必须为 0。
- **R6 安全护栏**：cwd 沙箱 + 只读 + 白名单，spawn 前拦截（AC：越权命令被拦；forbidden path 命中 → BLOCKED_NEEDS_HUMAN）。
- **R7 CLI 入口**：至少支持 `run` / `status` / `cancel` / `cleanup`，`cleanup` 删 Worktree 但保留日志与已合并代码（AC：见 §11 测试场景）。

### P1 — Should-Have（重要但可 fast-follow）
- **R8 窄修复循环**：QA FAIL 时只把原 Finding 交回 Execute，禁止扩大 Scope（AC：修复 diff 不触碰契约外文件）。
- **R9 Plane 状态同步**：PASS→In Review 并附 PR 链接；任意 Blocked→Blocked 并附类别（AC：与状态机映射一致）。
- **R10 多 Agent 备份接线**：Execute ×2（Claude Code + pi）、Verify ×2（QoderWake CLI + Codex）真正互为备份（AC：主 Agent 失败时备份接管且不重复劳动）。

### P2 — Future / 架构保险
- **R11 只读状态看板**（FastAPI + 极简 HTML，读 `runs/*.json`）——先于任何控制台。
- **R12 工单源插拔**：Plane 之外接 Linear / GitHub Issues。
- **R13 失败模式沉淀**：基于 QA Finding 模式做 Skill/规则演进。
- **R14 开源发布**：把 `src/ticket_autopilot/` 独立为 GitHub repo。

---

## 11. 成功指标（Metrics）

### 北极星（North Star）
**自动化闭环覆盖率** = 通过 Autopilot 从工单生成「review-ready PR」的工单数 ÷ 周期内符合低风险条件的工单总数。
- 成功阈值：GA 后一个季度 ≥ 60%；拉伸目标 ≥ 80%。

### 驱动指标（Leading）
| 指标 | 基线 | 目标 |
| --- | --- | --- |
| 工单→review-ready PR 中位耗时 | 手工 10–30 min | ↓ ≥ 50% |
| 单次闭环人工干预次数/工单 | — | ≤ 1 |
| 自动修复成功率（FAIL→再 PASS） | — | ≥ 70% |
| 机器可读 QA 输出占比 | — | 100% |

### 健康指标（Health / 护栏）
| 指标 | 阈值（硬） |
| --- | --- |
| False PASS 数 | 0 |
| main 直推 / 生产访问事件 | 0 |
| 工程证据完整保留率 | 100% |
| 结构不合规工单在开发前被挡率 | 100% |

### 度量方式
读 `runs/*.json` 快照 + `qa-verdict.json` + Plane 状态变更日志；评估窗口：GA 后 1 周 / 1 月 / 1 季。

---

## 12. 风险（Risks）

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 「pi」身份未确认 | Execute 备份缺失 | 先单 Execute 跑通，确认 pi 后再接备份 |
| QoderWake CLI 接线未落实 | Verify 仅 1 个备份，非真正互为备份 | 扩 AIO-7 接 QoderWake CLI（待定） |
| `ticket-controller` 产品级 CLI 仍为 stub | 真入口只有 Engine CLI，用户心智混乱 | 收口 AIO-5 后接通 CLI |
| 旧 `v0.1 Specification` 漂移 | 团队（含未来开源用户）被误导 | 本 PRD 为权威；旧规范归档 |
| Web UI 诱惑 | 过早造平台，违反复用优先 | 严守 NG1，先做只读看板（R11） |

---

## 13. 开放问题（Open Questions）

| # | 问题 | 需谁回答 | 阻塞性 |
| --- | --- | --- | --- |
| Q1 | 重试上限用 Engine 默认 `max_retries=5`，还是回归旧规范「2 次修复 / QA 最多 3 次」？ | PM（Haisu） | 否（可配置，但需在 PRD 锁定默认值） |
| Q2 | 「pi」Agent 身份与接入方式？ | 用户 | 否（不影响 P0） |
| Q3 | Verify 是否扩接 QoderWake CLI 以落实 2QA 备份？ | PM | 否（R10 P1） |
| Q4 | 产品级 `ticket-controller` CLI 何时接通（vs 直接用 Engine CLI）？ | PM | 否 |
| Q5 | 非技术用户的交付形态：只读看板（R11）vs 复用 QoderWake UI？ | PM | 否（NG1） |
| Q6 | 开源节奏与独立 repo 命名？ | PM | 否（R14） |

---

## 14. 阶段与完成定义（Phasing & DoD）

**当前阶段（v0.1 内核已落地）**：Engine + Drivers + Guardrails + 三个 Connector + 两契约，mock 跑通；AIO-5 垂直切片已取得 `accept` verdict（闭环曾卡在人工 git gate / 授权 MCP，属能力缺口非代码问题）。

**收口动作（建议，待批准）**
1. 把 `#5/#1/#4/#6/#9` 的 Plane 状态与代码实际对齐（消除「自述完成≠证据完成」）。
2. 接通 `ticket-controller` 产品级 CLI（R7 收口）。
3. 落实 Execute/Verify 双备份接线（R10）。
4. 之后才考虑只读看板（R11）。

**完成定义（DoD，v0.1 产品级）**
- Engine 本地 CLI 可跑通闭环；
- 能从 Plane 读并校验工单；
- 建可丢弃 Worktree/Branch；
- 调 Execute 实现 + 确定性验证；
- 建草稿 PR；Agent 不自动 merge，Repo Owner 可显式授权 Controller merge；
- 调 Verify 独立 QA + 重试循环；
- 同步 Plane 到 In Review / Blocked；
- 用 ≥ 3 张真实低风险工单试运行，False PASS=0、越权=0、证据保留=100%。

---

## 15. 附录：与 v0.1 规范的状态机差异（节选）

| 控制器事件 | v0.1 规范（Linear） | 当前实际（Plane） |
| --- | --- | --- |
| Run 接受 | Linear: In Progress | Plane: In Progress |
| QA PASS | Linear: In Review | Plane: In Review |
| 任意 Blocked | Linear: Blocked | Plane: Blocked |
| 状态同步粒度 | 宏观状态，不逐 Agent 同步 | 同左（宏观） |

> CLI 命名、包名、Adapter→Connector 改名、Engine 内核替换等差异，详见 §0 偏离声明与项目 MEMORY.md。

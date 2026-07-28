# AIO-1 开发提示词（Development Prompt）

> 本文件是交给「开发 Agent」的独立执行提示词，自包含，开发 Agent 不需要本仓库之外的上下文。
> 任务来源：Plane 项目 **Ticket Autopilot / AIO**（workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）→ Issue **#1「复用优先能力审计」**（issue id `4b1d03a5-be67-462b-9c4e-f2926126ab0c`）。
> 风险等级：**R0**（审计 / 文档 / 分析，极低风险，**不写生产代码**，仅允许只读探测命令）。
> 唯一真相来源：本提示词 + `AGENTS.md` + `IDEA.md` + 本仓库现有 Engine/Connector/reference 代码 + 已连接的 MCP 工具。
> 说明：本票在 **Linear 中不存在**（Linear 仅有「365企微会话存档」项目）；AIO 项目挂在 **Plane** 上，编号 `AIO-1` 对应 Plane `sequence_id=1`。后续 AIO 编号（AIO-2…）同理对应 Plane `sequence_id`。

---

## 0. [Goal check]（每段工作开头必须输出此行）

> [Goal check] This work advances **闭环前置（Reuse-First Capability Audit）** stage by delivering an evidence-backed gap document mapping every closed-loop stage to existing capabilities + minimal glue, narrowing the custom-Controller scope before any build.

若无法用一句话填完上面这行，先停下，不要动手。

---

## 1. 背景与目标（Goal）

仓库已经有一个**能跑通声明式闭环**的 Engine 雏形（详见 §5 参考），但还缺一份在「动手写任何自定义代码之前」盘点可复用能力的**审计文档**。AGENTS.md / IDEA.md 明确要求先做「复用优先能力审计」再进入实现。

本票目标：

1. 把 ticket 闭环的 **7 个阶段**（见 AGENTS.md / IDEA.md 以及 AIO-2 将固化的闭环定义）逐一映射到**当前真实存在**的能力（Engine / Connector / Plane client / MCP / `gh` CLI / GitHub Actions）。
2. 对每个阶段明确标注：**已有能力 / 缺口 / 最小胶水推荐** 三项。
3. 给出「哪些阶段**不**需要新建平台、只需配置或薄胶水」的结论，落实 IDEA.md 的「配置 → 薄胶水 → 小控制器」决策顺序。
4. 指出具体已知坑（如 `plane_client` PROJECT_ID 错位、MCP 403 UA、Verifier 是 LLM 而非 Codex 独立 QA 等），避免后续票重复踩坑。

交付物（唯一硬性产物）：**`research/capability-audit.md`**（单文件，自包含，可被后续 AIO 票直接引用）。

---

## 2. 范围边界（Scope Boundary）

### In scope（必须做）

1. **7 阶段映射表**（必须覆盖，缺一即不合格）。每阶段三列都要填：已有能力（含具体文件/工具/命令）/ 缺口 / 最小胶水。

   | 阶段 | 必须回答 |
   |---|---|
   | 工单接入与契约（Ticket intake & contract） | 现有能力能否读 Plane 工单 → 结构化契约？缺口？ |
   | 计划 Plan | Engine `planner` 节点（driver: llm）是否已覆盖？ |
   | 执行/开发 Execute | Engine `executor`（driver: cli，`cwd=./sandbox`，`read-only`，工具白名单）是否已覆盖？实际代码 diff/commit/PR 由谁做？ |
   | 确定性验证与独立 QA | 当前 `verifier` 是 LLM 输出 `accept/reject`；独立 Codex QA + 结构化 `qa-verdict.json` 缺口？ |
   | 有界修复循环（Bounded fix loop） | `verify`→`execute` 的 loop 边（`when: decision=='reject'`，`max_retries` 默认 5）是否已覆盖？ |
   | Pull Request 与 CI 证据 | GitHub PR/CI 由谁做？现有能力？缺口？ |
   | 工单状态与结果 | `closer` 节点（`close_ticket` → Plane 写评论 + 置 done）是否已覆盖？ |

   另加两个**横切关注**（简写即可，但必须出现，作为独立小节或表格行）：
   - **人工 Review / Merge 安全门**（human gate，不自动 merge）
   - **安全边界**（不直推 Main / 不碰生产 / 凭证不落地明文）

2. **现有可复用能力清单**（逐条，带引用路径/工具名，且每条都经过实际核验，见 AC-2）：
   - Engine DAG + 重试循环解释器：`src/ticket_autopilot/engine/engine.py`
   - 4 类 driver：`src/ticket_autopilot/engine/drivers.py`（llm / cli[含 `SecurityError` 目录沙箱 + 只读 + 工具白名单] / hermes / script）
   - 闭环定义：`src/ticket_autopilot/workflows/ticket-pipeline.yaml` + `workflows/ticket-pipeline-hermes.yaml`
   - 唯一碰 Plane 的节点：`src/ticket_autopilot/engine/handlers/close_ticket.py`
   - 已验证可用的 Plane REST 客户端：`src/ticket_autopilot/reference/ticket-pipeline/plane_client.py`（方法：`list_issues` / `get_issue` / `create_issue` / `set_state`[用 `state` 字段非 `state_id`] / `add_comment` / `delete_issue`）
   - 确定性自测：`src/ticket_autopilot/engine/tests/test_engine.py`（mock 跑通重试循环 + CLI 护栏 + hermes；**全绿**）
   - 已连接 / 可调用的 MCP：Plane（`mcp__plane__*`）、Linear（`mcp__linear__*`）、agent-mail（已连接，可做通知）
   - 原生 GitHub 能力：`gh` CLI / GitHub Actions（PR/CI），但当前**非 MCP 连接**

3. **已知坑清单**（至少包含以下各项，且每条给最小胶水建议）：
   - `plane_client.py` 的 `PROJECT_ID` 写死为 `5c5c7207-868e-4da6-ae95-66e7d02eeebb`，而 AIO 项目 id 是 `d40168f5-5d44-4810-a39e-3b6558e9bf6e` → 需参数化 / 从配置读取。
   - Plane MCP 代理因 Cloudflare 403（非浏览器 UA，error 1010）不可用；REST 客户端靠 browser UA 绕过 → 后续 connector 应复用 REST 客户端而非 MCP 代理。
   - 当前 `Verifier` 是 LLM 输出 `accept/reject`，**不是**规格 §8.2/§9 要求的独立 Codex QA + 结构化 `qa-verdict.json` → 缺口（对应 AIO-7）。
   - PR 创建**未实现**（Engine 不建 branch / commit / PR）→ 缺口（对应 AIO-8）。
   - 产品 CLI `src/ticket_autopilot/cli.py` 是 stub，未接线 → 缺口。
   - `connectors/`、`services/`、`schemas/` 仅 `__init__.py` 空脚手架 → 缺口。

4. **结论段**：明确「不新建平台」范围 + 真正的自定义 Controller / Connector 最小范围（供 AIO-2..AIO-9 引用）。

### Out of scope（严禁做）

- **不写任何生产代码**（本票是审计 / 文档；允许 `python -m unittest`、`grep`、`gh` 查询等**只读**探测，但不得新增 / 修改 `src/` 业务代码）。
- **不实现** Connector / GitHub PR / Codex QA / CLI 接线（那是 AIO-6 / AIO-7 / AIO-8 / 后续票）。
- **不实现** resume（AGENTS.md / IDEA.md 明确排除）。
- **不扩展**到 v0.2（webhook 触发 / 并行 Run / 自动 merge / 自动部署 / 自动迁移 / 自动选下一票）。
- **不碰**生产数据、生产密钥、数据库迁移。
- 不要因为审计发现缺口就顺手去修——记在文档里，交后续票。

---

## 3. 验收标准（Acceptance Criteria，逐条 Pass/Fail）

- **AC-1**：`research/capability-audit.md` 存在，覆盖全部 7 阶段 + 2 横切关注，每阶段含「已有能力 + 缺口 + 最小胶水」三列，无空白 / TBD。
- **AC-2**：每条被声称的「已有能力」都经实际核验，文档中标注核验方式（`grep` / `Read` / 运行只读命令等）；不得出现「应可用 / 应该能做」式无证据断言。
- **AC-3**：文档明确给出「不需要新建平台」的阶段清单（哪些可由现有 Engine / Plane client / MCP / `gh` 闭合或只需薄胶水），与 IDEA.md 复用优先一致。
- **AC-4**：文档列出已知坑（至少含 plane_client PROJECT_ID 错位、MCP 403 UA、Verifier≠Codex QA、PR 未实现、CLI stub、connectors/services/schemas 空脚手架），且每条给最小胶水建议。
- **AC-5**：文档不要求实现代码（本票纯审计 / 分析），且原则与 AGENTS.md / IDEA.md 无矛盾（复用优先、不建平台、不自动 merge、不碰生产）。
- **AC-6**：文档给出「下一步最小胶水优先级」建议（哪几项是真正的自定义范围），可被后续票（AIO-2..AIO-9）直接引用。

---

## 4. 验证方式（Verification，确定性门禁）

- 本票理想情况只产出文档；若被迫改动代码须保持测试绿：
  ```bash
  python -m unittest discover -s src/ticket_autopilot/engine/tests
  ```
- 交付前自查（人工 / 脚本核验）：
  - 7 阶段名 + 2 横切关注在文档中均可 grep 命中。
  - 文档引用的每个文件路径在仓库真实存在（`grep` / `Read` 核验，发现虚构引用即不合格）。
  - 已知坑关键词（PROJECT_ID / 403 / Verifier / PR / stub / 空脚手架）在文档中可出现。
  - 无「应可用」式空话。

---

## 5. 依赖（Dependencies）

- 参考（真实存在，**必须读**）：
  - `AGENTS.md`、`IDEA.md`
  - `src/ticket_autopilot/engine/engine.py`、`drivers.py`、`cli.py`、`handlers/close_ticket.py`
  - `workflows/ticket-pipeline.yaml`、`workflows/ticket-pipeline-hermes.yaml`
  - `reference/ticket-pipeline/plane_client.py`
  - `engine/tests/test_engine.py`
- 已连接 MCP（可在**只读**前提下探测能力边界）：Plane（`mcp__plane__*`）、Linear（`mcp__linear__*`）、agent-mail。
- ⚠️ **不要**把 `tasks/ticket-autopilot-v0.1-tasklist.md`（T0–T19）当作架构依据——它描述的是**旧架构**（`ticket_controller` 包 + Linear/Claude/Codex 适配器），与当前 Engine+Connector+Plane 架构不符，已过时。其**闭环阶段划分**可作参考，但**具体工具 / 文件断言**一律以当前仓库为准。

---

## 6. Definition of Done

- [ ] `research/capability-audit.md` 已落地，7 阶段 + 2 横切全覆盖
- [ ] 每条已有能力经实际核验并标注核验方式
- [ ] 「不新建平台」范围 + 最小胶水结论明确
- [ ] 已知坑清单 + 最小胶水建议就位
- [ ] 给出下一步优先级，供后续票引用
- [ ] 现有单元测试仍全绿（纯文档改动天然满足）
- [ ] 无 scope 蔓延（逐条对照 Out of scope）

---

## 7. 风险与回滚（Risk & Rollback）

- 风险：能力断言失真（写了不存在的能力），误导后续票。
- 回滚：纯文档产物，`git revert` 即可；不影响运行代码。

---

## 8. 人工点位（Human touchpoints）

- **Trigger**：PM 将本票置 `In Progress` 即启动（唯一需要的人工启动动作）。
- **Gate**：PR review（文档 / 分析产物，需人 review 才合并）。
- **Escalation**：3 次失败重跑后升级给 PM。

---

## 9. 硬性约束（来自 AGENTS.md / IDEA.md，违反即 BLOCKED）

- **复用优先**：能用现有 Engine / Plane client / MCP / `gh` 闭合的阶段，不新建代码。
- **只认证据不认自述**：每条能力断言必须可核验，不得写「应该能做」。
- **不建新平台、不实现 resume、不自动 merge、不碰生产**。
- **本票禁止写生产代码**（仅只读探测）。
- **凭证**从环境变量 / Keychain 读取，不落地明文（本票基本不涉及，但提及即遵守）。
- 任一确定性失败只标 `BLOCKED`，绝不标成功。

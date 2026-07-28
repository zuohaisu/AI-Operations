# AIO-7 开发提示词 — 接 Codex 做独立 QA（Verify 步骤）

> 来源：Plane 工单 **AIO-7**（项目 "Ticket Autopilot / AIO"，`project_id=d40168f5-5d44-4810-a39e-3b6558e9bf6e`，`issue_id=ef92ac7a-1399-45db-8a83-4462d0b118a7`）。
> 注：用户最初称「Linear 里的任务」，但 AIO 系列工单实际在 **Plane**（Linear/Builder 无 AIO 编号）。本提示词供**开发 agent** 执行实现；验收见配套 `aio-7-acceptance-prompt.md`。

## 一、原工单要点（Plane AIO-7）

- **Goal**：Engine 的 Verify 步骤调用 Codex 做独立 QA，产出证据报告（只 verdict，不修问题）。
- **Scope In**：Codex 调用、verdict 结构化、gate PR。
- **Scope Out**：Codex 修复代码。
- **Acceptance**：① Verify 阶段产出 pass/fail verdict + 证据；② fail 触发 reject 重跑。
- **Verify**：端到端跑一次，QA verdict 正确 gate PR。
- **Depends on**：#2（核心闭环，已完成）、#6（Ticket/PR 连接器，提供上下文；**尚未完成**）。
- **Done**：QA 集成 + 结构化 verdict schema。
- **Risk**：Codex 成本/限流；verdict 不稳定 → 需确定性校验兜底。
- **Human**：Trigger=置 In Progress；Gate=PR review。

## 二、现状与已有资产（务必先读再动手）

- **引擎核心**：`src/ticket_autopilot/engine/engine.py` —— DAG + `verify→reject→execute` 重试循环，由 `when: "nodes.verify.decision == 'accept'|'reject'"` 驱动。**循环语义是承重部分，不要改。**
- **驱动层**：`src/ticket_autopilot/engine/drivers.py` —— `llm / cli / hermes / script`；`cli` 已支持 `command`（默认 `claude`）+ 只读沙箱 + 工具白名单 + `_maybe_json`（围栏剥离 JSON 解析）。这是 Codex 调用的现成底座。
- **工作流**：`src/ticket_autopilot/workflows/ticket-pipeline.yaml` 与 `ticket-pipeline-hermes.yaml`。当前 `verify` 节点用 `driver: llm`/`hermes`，仅返回 `{"decision","reason"}` 的浅层 accept/reject —— **未调用 Codex、无结构化 verdict**。
- **连接器层**：`src/ticket_autopilot/connectors/__init__.py` 说明「适配器只做外部 API 翻译，含 Codex」，但目前是空壳。
- **Schema**：`src/ticket_autopilot/schemas/__init__.py` 已声明 `qa-verdict.schema.json`，但**该文件实际不存在** —— 本期需新建。
- **产品规范**：`specs/Ticket Autopilot v0.1 Specification.md` §2（证据优于声称）、§2.4（No false success）、§8.2（QA Agent 职责）、§9（QA Verdict Contract / `qa-verdict.json` 结构）、§11（状态机）。
- **引擎 README**：`src/ticket_autopilot/engine/README.md`。

## 三、实现范围（Do）

1. **结构化 verdict schema（承重契约 #2）**
   - 新建 `src/ticket_autopilot/schemas/qa-verdict.schema.json`，字段严格对齐规范 §9.1：
     `schema_version, issue_key, run_id, qa_attempt, verdict(PASS|FAIL|BLOCKED), acceptance_criteria[{id,status,evidence[]}], findings[{id,severity,type,acceptance_criterion_id,summary,evidence,required_fix}], non_blocking_comments[], recommended_next_state`。
   - 新建 `src/ticket_autopilot/schemas/qa_verdict.py`：`validate_verdict(dict) -> (bool, list[str])`，用 `jsonschema` 校验；非法/缺失 → `(False, errors)`。**任何不通过校验的输出都不得被视为 PASS。**

2. **Codex 独立 QA 连接器**
   - 新建 `src/ticket_autopilot/connectors/codex_qa.py`：封装「调用 Codex（只读）→ 解析 verdict → 确定性校验 → 映射到引擎决策」三步。
   - Codex 调用**复用** `drivers.cli_call`，参数：`command="codex"`、`permission_mode="read-only"`、`tools=["Read","Glob","Grep"]`（确保只 verdict 不修代码）、`expect="json"`，并将 Codex CLI 实际接口（`codex exec` / `-p` 等）差异收敛在此文件（先 `which codex` 确认，必要时调整命令行/参数；解析时复用 `_maybe_json` 的围栏剥离逻辑）。
   - QA system 提示词必须要求 Codex：读取传入的 `ticket_context`（验收标准 + diff + 测试证据）→ **仅输出 qa-verdict JSON**；明确「不得修改代码、不得补充测试」（只读 + 白名单已从执行层强制）。

3. **输出契约（与现有循环零改动对接）**
   - `codex_qa` 返回：`{"decision": "accept"|"reject", "verdict": {<qa-verdict 实例>}}`。
   - 映射规则：verdict=="PASS"→`accept`；verdict ∈ {FAIL, BLOCKED}→`reject`；**解析失败 / schema 不通过 → 强制 `reject` 且 verdict 记为 `BLOCKED`（确定性兜底，绝不 false PASS）**。
   - `verify` 节点的 `capture: verdict` 保留，使完整 verdict 可被 `close`/连接器（#6）消费与归档。

4. **工作流接入**
   - 在 `ticket-pipeline.yaml`（及 hermes 变体）中，将 `verifier` 改为指向 Codex QA：推荐 `driver: script, entry: codex_qa`（在 `codex_qa.py` 内调用 `drivers.cli_call(command="codex")`）；并在 `verify` 节点 `inputs` 增加 `ticket_context`（见第四节依赖边界）。
   - **不得改动** `engine.py` 的 `when` 子句与循环语义；只通过 `decision` 字段对接。
   - 同步更新两个 YAML 的 `mock` 段：把原 `verifier: {reject_times: 2, ...}` 改为新 agent 名（如 `codex_qa: {reject_times: 2, ...}`），保证 `python -m ticket_autopilot.engine run ... --mock` 仍能跑通「reject x2 → accept，execute 跑 3 次，close 仅 on accept」。

5. **确定性兜底（风控）**
   - 实现「无伪成功」不变量：只有「通过 schema 校验且 `verdict=="PASS"`」才产生 `decision:"accept"`；其余一律 `reject`。
   - （可选增强）若 `ticket_context` 含确定性检查结论（如 diff 为空 / 必需测试未通过），即使 QA 说 PASS 也强制 BLOCKED。本期至少保证 schema 校验兜底。

## 四、依赖边界（关于 #6）

- AIO-7 **不依赖 #6 先合并** 即可交付与自测。QA 所需的 `ticket_context`（验收标准 + diff + 测试证据）通过 `verify` 节点 `inputs.ticket_context` 传入；本期由**测试桩/临时注入**提供，#6 连接器后续负责从 Plane 工单真实填充。
- 「gate PR」在本期含义：保证 **PASS 才是到达 `close` 节点（即 #6 未来建 PR 的入口）的正确门禁信号**，并把 verdict 作为证据随 `outputs` 暴露；**实际 GitHub PR 创建属于 #6，不在本期实现**。验收据此判定，不因「未建 PR」而判失败。

## 五、不在范围（Don't）

- 不创建 GitHub PR（#6）。
- 不让 QA 修改/补充代码或测试（只读 + 白名单强制；规范 §8.2、§10）。
- 不新增 `codex` driver 类型（复用 `cli` driver）；不改动 engine 循环语义。
- 不做网络隔离 / 沙箱虚拟化（#5 护栏范围）。

## 六、完成定义（Done）

- `qa-verdict.schema.json` + `validate_verdict` 就绪并通过单测。
- `connectors/codex_qa.py` 就绪；工作流 `verify` 节点接入 Codex；无 Codex 环境时可用 fake-codex 桩跑通。
- 端到端（mock / fake-codex）验证：PASS → 到达 `close` 且 verdict 为 schema 合法 PASS；FAIL/BLOCKED → `reject` → 重跑 `execute`，未达 `close`。
- 无伪成功：畸形/未校验输出 → `reject(BLOCKED)`，绝不 `accept`。
- 既有 `test_engine.py` 不回归，新增测试绿（见验收提示词）。

## 七、建议改动文件清单

- 新增：`src/ticket_autopilot/schemas/qa-verdict.schema.json`
- 新增：`src/ticket_autopilot/schemas/qa_verdict.py`
- 新增：`src/ticket_autopilot/connectors/codex_qa.py`
- 新增（测试）：`src/ticket_autopilot/engine/tests/test_codex_qa.py` + fake-codex 桩
- 修改：`src/ticket_autopilot/workflows/ticket-pipeline.yaml`、`ticket-pipeline-hermes.yaml`（`verifier` → Codex；更新 `mock` 段）
- 可选：`src/ticket_autopilot/schemas/__init__.py` 补充导出/说明
- 可选：`src/ticket_autopilot/engine/handlers/close_ticket.py` 增加将 `verdict` 写入运行快照（供 #6 归档 `runs/<run_id>/qa-verdict-<n>.json`）

## 八、交付约束

- 所有改动走 PR（Git 写操作需用户显式确认；PR 需人工 review 后才合并 —— 对应工单 Human.Gate=PR review）。
- 不要提交密钥；Codex 凭证从环境变量读取（`CODEX_*` 或复用现有 gateway 约定）。

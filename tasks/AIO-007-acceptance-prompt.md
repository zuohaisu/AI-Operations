# AIO-7 验收提示词 — 接 Codex 做独立 QA（Verify 步骤）

> 配套 `aio-7-dev-prompt.md`。来源：Plane 工单 **AIO-7**（`issue_id=ef92ac7a-1399-45db-8a83-4462d0b118a7`，项目 "Ticket Autopilot / AIO"）。本提示词供**测试 agent** 执行验收。

## 一、验收目标

验证 AIO-7 开发成果是否满足工单 Acceptance / Verify，并符合 Ticket Autopilot v0.1 规范的核心原则：**证据优于声称（§2）**、**No false success（§2.4）**、**QA 只 verdict 不修代码（§8.2、§10）**、**QA Verdict 须过 Schema 校验（§9）**。

## 二、验收依据

- 工单 Acceptance：① Verify 阶段产出 pass/fail verdict + 证据；② fail 触发 reject 重跑。
- 工单 Verify：端到端跑一次，QA verdict 正确 gate PR。
- 规范：`specs/Ticket Autopilot v0.1 Specification.md` §2、§2.4、§8.2、§9、§11。
- 开发范围与完成定义：见 `aio-7-dev-prompt.md`。

## 三、必跑检查（Pass/Fail 判定）

1. **Schema 校验单测**
   - 合法 `qa-verdict` → `validate_verdict` 返回 `(True, [])`。
   - 缺 `verdict` / `acceptance_criteria` / `findings` 等必填 → `(False, …)`。
   - `verdict` 取值非 `PASS|FAIL|BLOCKED` → `(False, …)`。
   - 断言：任何 `(False, …)` 的输出**绝不**被映射为 `decision:"accept"`。

2. **无伪成功（No false success）**
   - 构造畸形 Codex 输出（非 JSON / 缺必填 / 非法枚举）→ 连接器返回 `decision:"reject"` 且 verdict 记为 `BLOCKED`。
   - 构造 `verdict=="PASS"` 但 schema 不合法 → 必须被兜底为 `reject(BLOCKED)`，不得到达 `close`。

3. **循环语义（FAIL → 重跑）**
   - 用 fake-codex 桩：第一次返回 FAIL（含 findings），断言 `execute` 重跑（loop 边触发）、`close` 未达；第 N 次返回 PASS 后到达 `close`。
   - 复用既有 mock 机制：在两个 YAML 的 `mock` 段给新 agent（如 `codex_qa`）配置 `reject_times`，执行 `python -m ticket_autopilot.engine run workflows/ticket-pipeline.yaml --mock` 应仍满足「reject x2 → accept，execute 跑 3 次，close 仅 on accept」。

4. **PASS → gate 信号正确**
   - 合法 PASS → 工作流到达 `close` 节点；`outputs['verify']['verdict']` 为 schema 合法 PASS（证据可归档）。
   - **PR 创建与否不计入 AIO-7 验收**（属 #6）；仅验证「到达 `close` 的充要条件是合法 PASS verdict」这一门禁语义。

5. **独立性与只读**
   - 审阅 `codex_qa` 调用参数：`permission_mode=="read-only"`、`tools` 仅含只读工具；QA system 提示词明确要求「不修改代码、不补充测试」。
   - 确认 Codex 与执行器（claude）是**不同 agent**（独立 QA），不在同一进程/同一模型实例内完成开发与验证。

6. **回归**
   - 既有 `src/ticket_autopilot/engine/tests/test_engine.py` 全绿（循环 + cli 护栏 + hermes dispatch + mock 运行）。
   - 新增测试随 `python -m unittest discover -s tests`（或 `python -m unittest ticket_autopilot.engine.tests.test_codex_qa`）全绿。

## 四、端到端 Verify（各有 Codex / 无 Codex 环境各一次）

- **有 Codex 环境**：配置 Codex 凭证（见开发提示词），对一张真实低风险工单跑通 `verify` 节点，确认产出合法 `qa-verdict` 且 FAIL 能正确 `reject` 重跑。
- **无 Codex 环境（默认 CI）**：用 fake-codex 桩覆盖上述 1–5，**禁止依赖真实 Codex 密钥才能跑测试**。

## 五、证据留存

- 每个 QA verdict（含 attempt 序号）应可从 `outputs['verify']` 或运行快照取得，供 #6 后续归档 `runs/<run_id>/qa-verdict-<n>.json`。
- 测试 agent 输出：通过的断言清单 + 任何 BLOCKED/不通过项 + 结论（**AIO-7 PASS / 需返工**）。

## 六、不通过条件（明确）

- `qa-verdict.schema.json` 缺失或未对齐规范 §9 结构；
- 畸形/未校验输出可导致 `accept`；
- FAIL 不触发重跑（循环未生效）；
- Codex 被允许写代码 / 补充测试；
- 既有 `test_engine.py` 出现回归。

## 七、测试脚手架建议

- `tests/test_codex_qa.py`：
  - `test_validate_verdict_ok_and_reject_cases`
  - `test_malformed_output_forced_reject_blocked`
  - `test_fail_triggers_rerun_then_pass_reaches_close`（用 fake-codex 桩驱动引擎）
  - `test_pass_only_gates_close`（断言非 PASS 不达到 close）
- fake-codex 桩：一个可执行脚本/小程序，读取预设 verdict 文件或环境变量，向 stdout 打印合法/非法 `qa-verdict` JSON，供 `drivers.cli_call(command=<fake-codex>)` 调用，实现零密钥确定性测试。

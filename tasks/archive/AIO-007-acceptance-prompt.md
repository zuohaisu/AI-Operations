# AIO-7 验收提示词 — 接独立 QA agent（Verify 步骤）

> 配套 `AIO-007-dev-prompt.md`。来源：Plane 工单 **AIO-7**（`issue_id=ef92ac7a-1399-45db-8a83-4462d0b118a7`，项目 "Ticket Autopilot / AIO"）。本提示词供**测试 agent** 执行验收。
>
> **2026-07-29 修订**：实现与工单原文有三处经用户拍板的偏离（详见 `logs/goal-drift.md` 同日条目）：
> ① QA agent 为 **qodercli**（非 codex；codex 改任 planner），QA 不设备份；
> ② `engine.py` 新增 **agent 级 fallback**（driver 调用外层附加 try/except，未改循环语义）；
> ③ schema 校验为**零依赖手写子集**（非 jsonschema 库，项目 dependencies=[] 为刻意约束）。
> 验收按本修订后的清单执行；不得以「与工单原文字面不符」为由判 FAIL，但须核对偏离已在 goal-drift 登记。

## 一、验收目标

验证 AIO-7 开发成果是否满足工单 Acceptance / Verify，并符合 Ticket Autopilot v0.1 规范的核心原则：**证据优于声称（§2）**、**No false success（§2.4）**、**QA 只 verdict 不修代码（§8.2、§10）**、**QA Verdict 须过 Schema 校验（§9）**。

## 二、验收依据

- 工单 Acceptance：① Verify 阶段产出 pass/fail verdict + 证据；② fail 触发 reject 重跑。
- 工单 Verify：端到端跑一次，QA verdict 正确 gate PR。
- 规范：`specs/Ticket Autopilot v0.1 Specification.md` §2、§2.4、§8.2、§9、§11。
- 开发范围与完成定义：见 `AIO-007-dev-prompt.md`（连同上方修订说明）。

## 三、必跑检查（Pass/Fail 判定）

1. **Schema 校验单测**（`src/ticket_autopilot/schemas/qa-verdict.schema.json` + `schemas/qa_verdict.py::validate_verdict`）
   - 合法 `qa-verdict` → `validate_verdict` 返回 `(True, [])`。
   - 缺 `verdict` / `acceptance_criteria` / `findings` 等必填 → `(False, …)`。
   - `verdict` 取值非 `PASS|FAIL|BLOCKED` → `(False, …)`。
   - 断言：任何 `(False, …)` 的输出**绝不**被映射为 `decision:"accept"`。

2. **无伪成功（No false success）**（`src/ticket_autopilot/connectors/qa.py::run_qa`）
   - 构造畸形 QA CLI 输出（非 JSON / 缺必填 / 非法枚举）→ 连接器返回 `decision:"reject"` 且 verdict 记为 `BLOCKED`。
   - 构造 `verdict=="PASS"` 但 schema 不合法 → 必须被兜底为 `reject(BLOCKED)`，不得到达 `close`。
   - QA CLI 进程失败（非零退出/超时）→ 同样 `reject(BLOCKED)`，且兜底 verdict 本身应通过 schema 校验（可归档）。

3. **循环语义（FAIL → 重跑）**
   - 复用既有 mock 机制：两个 YAML 的 `mock` 段 `verifier: {reject_times: 2, …}`，执行
     `PYTHONPATH=src python3 -m ticket_autopilot.engine run src/ticket_autopilot/workflows/ticket-pipeline.yaml --mock --params '{"ticket_id":"DEMO-1"}'`
     应满足「reject x2 → accept，execute 跑 3 次，close 仅 on accept」。`ticket-pipeline-hermes.yaml` 同样跑一次。
   - 核对运行 log 的节点序列为 `plan → (execute → verify) x3 → close`，**close 不得早于最终 accept 出现**。

4. **PASS → gate 信号正确（结构性门禁）**
   - 合法 PASS → 工作流到达 `close` 节点；`outputs['verify']['verdict']` 为 schema 合法 PASS（证据可归档）。
   - 引擎层回归：入边全部带 `when` 的节点（如 `close`）初始不得就绪，必须等条件边真正触发
     （2026-07-29 修复的真实门禁缺陷；回归测试 `test_qa.py::TestQaGate::test_schema_invalid_pass_never_reaches_close`）。
   - **PR 创建与否不计入 AIO-7 验收**（属 #6）；仅验证「到达 `close` 的充要条件是合法 PASS verdict」这一门禁语义。

5. **独立性与只读**
   - 审阅 `connectors/qa.py::QA_AGENT`：`command=="qodercli"`；qodercli 无 read-only 权限模式，只读靠 `tools` 白名单（仅 `Read/Glob/Grep`）+ `--allowed-tools "Read,Glob,Grep"`（非交互 `-p` 模式下仅自动放行读工具，写操作被拒 — 已真实冒烟验证）+ `--no-session-persistence` 一次性会话；`cwd` 限定 sandbox（`drivers.cli_call` 的 `SecurityError` 守卫生效）。
   - QA system 提示词（`QA_SYSTEM_PROMPT`）明确要求「不修改代码、不补充测试、仅输出 qa-verdict JSON」。
   - 确认 QA（qodercli）与开发执行器（claude，备 pi）是**不同 agent**，不在同一进程/同一模型实例内完成开发与验证。planner（codex）不参与 verify。

6. **fallback 附加机制未破坏循环语义**
   - `engine.py::_run_node` 的 fallback 仅包裹 driver 调用：主 agent 失败 → 备份 agent 一次 → 双失败照常抛错；未触碰 `when`/loop/readiness/`max_retries`。
   - 断言测试存在且绿：fallback 触发、双失败抛错、无 fallback 直接抛错（`test_drivers.py::TestAgentFallback`）。

7. **回归**
   - 全量：`PYTHONPATH=src python3 -m unittest discover -s src/ticket_autopilot/engine/tests` 全绿（当前基线 **45 tests**：既有循环/cli 护栏/hermes dispatch/mock 运行不回归 + schema/connector/门禁新增 + 返工新增：findings 强制 `acceptance_criterion_id`/`evidence`(object) 负测、PASS 自相矛盾一致性负测、`--allowed-tools` 只读策略审计）。

## 四、端到端 Verify（有 / 无 qodercli 环境各一次）

- **有 qodercli 环境**：对一张真实低风险工单跑通 `verify` 节点，确认产出合法 `qa-verdict` 且 FAIL 能正确 `reject` 重跑。注意冒烟点：qodercli `-p` stdout 是否干净可被 `expect: json` 解析。
- **无 qodercli 环境（默认 CI）**：用 fake QA 桩（`unittest.mock` 替换 `drivers.cli_call`，见 `engine/tests/test_qa.py`）覆盖上述 1–6，**禁止依赖真实 qodercli 登录态才能跑测试**。

## 五、证据留存

- 每个 QA verdict（含 attempt 序号）应可从 `outputs['verify']` 或运行快照（`src/ticket_autopilot/runs/`）取得，供 #6 后续归档 `runs/<run_id>/qa-verdict-<n>.json`。
- 测试 agent 输出：通过的断言清单 + 任何 BLOCKED/不通过项 + 结论（**AIO-7 PASS / 需返工**）。

## 六、不通过条件（明确）

- `qa-verdict.schema.json` 缺失或未对齐规范 §9 结构；
- 畸形/未校验输出可导致 `accept`；
- FAIL 不触发重跑（循环未生效），或 `close` 早于最终 accept 运行；
- QA agent 被允许写代码 / 补充测试（工具白名单含写工具即判违规）；
- fallback 改动触碰了 `when`/loop/readiness 语义；
- 偏离项未在 `logs/goal-drift.md` 登记；
- 既有 engine/drivers 测试出现回归。

## 七、测试脚手架对照（已实现）

- `src/ticket_autopilot/engine/tests/test_qa.py`：
  - `TestValidateVerdict`（合法/缺字段/非法枚举/非对象/子项缺字段/兜底 verdict 自身合法）
  - `TestRunQa`（PASS→accept、FAIL/BLOCKED→reject、CLI 失败→BLOCKED、非 JSON→BLOCKED、schema 不合法 PASS 永不 accept、QA agent 只读参数审计）
  - `TestQaGate`（引擎端到端：合法 PASS 达 close；非法 PASS 不达 close）
- fake QA 桩采用 `unittest.mock` 替换 `drivers.cli_call`（零密钥确定性测试），未使用独立可执行脚本；验收认可两种形态。

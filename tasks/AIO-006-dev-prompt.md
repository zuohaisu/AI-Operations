# AIO-6 开发提示词（Development Prompt）

> 本文件是交给「开发 Agent」的独立执行提示词，自包含，开发 Agent 不需要本仓库之外的上下文。
> 任务来源：Plane 项目 **Ticket Autopilot / AIO**（workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）→ Issue **#6「实现 Engine drivers（llm / cli / hermes / script）」**（issue id `5487070e-752e-48ca-9043-8a9057b02aa0`）。
> 风险等级：**R1**（写生产代码，但全部测试走 mock，不依赖外部服务/密钥，低风险）。
> 唯一真相来源：本提示词 + `src/ticket_autopilot/engine/drivers.py` + `engine.py` + `engine/README.md` + 现有 `engine/tests/test_engine.py`。

---

## 0. [Goal check]（每段工作开头必须输出此行）

> [Goal check] This work advances **Engine driver hardening** by (a) verifying/completing the 4 executors (llm/cli/hermes/script) already present in `drivers.py`, (b) adding a dedicated `tests/test_drivers.py` with per-driver unit tests + a mock-YAML end-to-end run, (c) making the unified driver contract explicit in docs — all without weakening the existing CLI sandbox guardrail (owned by AIO-9).

若无法用一句话填完上面这行，先停下，不要动手。

---

## 1. 背景与现状（Goal + Reality Check）

**本项目真实状态（必须先读、必须据此工作，不要按字面从零实现）：**

- `src/ticket_autopilot/engine/drivers.py` **已经实现**全部 4 类执行器：
  - `llm_call(agent, inputs, node)` —— 走 OpenAI 兼容 `/chat/completions`（urllib，无 SDK 依赖），读 `XY_LLM_BASE_URL` / `XY_LLM_API_KEY` / `XY_LLM_MODEL`；`agent.expect=="json"` 时解析 JSON（容忍 ```fence```）。
  - `hermes_call(agent, inputs, node, mock=False)` —— POST 到 Hermes gateway（`HERMES_API_URL` 默认 `http://localhost:8642/v1`）；`agent.session_key`/`HERMES_SESSION_KEY` → `X-Hermes-Session-Key` 头；`mock=True` 时返回标记 dict，不触网。
  - `cli_call(agent, inputs, node, engine_root)` —— 在**严格沙箱**里 spawn 外部 CLI（默认 `claude`）：`cwd` 必须落在 `allowed_roots`（默认 `["sandbox"]`）内，否则在 spawn 前抛 `SecurityError`；参数含 `--permission-mode read-only` + `--allowedTools` 白名单。
  - `script_call(agent, inputs, engine_root)` —— `importlib` 加载 `engine/handlers/<entry>.py` 并调用同名函数 `entry(**inputs)`（现被 `close_ticket` 节点使用）。
- `src/ticket_autopilot/engine/engine.py::_run_node` **已把 4 个 driver 接入分发**（外加 `mock` 模式在 engine 层统一返回 canned 输出，driver 不被实际调用）。
- **缺失项（本票真正的交付）**：
  1. 专属测试文件 `src/ticket_autopilot/engine/tests/test_drivers.py` **尚不存在**（现有只有 `test_engine.py`，覆盖重试循环/cli 目录护栏/hermes 路由，未逐 driver 单测）。
  2. 4 个 driver 的**统一接口契约**在文档里未成体系（engine/README.md 有描述但分散；"统一接口" 未显式落地）。
- 现有测试运行方式：`PYTHONPATH=src python -m unittest discover -s src/ticket_autopilot/engine/tests`（全绿）。本环境 **PyYAML 可用、pytest 9.1.1 可用**，`pytest` 可直接跑 `unittest.TestCase`。

**本票目标**：不是从零写 4 个 driver（它们已存在），而是 **校验 + 收口 + 测试 + 文档**，让 "4 driver + 统一接口 + 单测全绿" 成为可独立核验的事实。

---

## 2. 范围边界（Scope Boundary）

### In scope（必须做）
1. **校验并补齐 4 个 driver 的实现**，对齐 `engine/README.md` 与 `workflows/*.yaml` 描述的契约：
   - llm：env 读取逻辑、`expect: json` 解析（含 fence 容错）、非 json 时原样返回。
   - cli：cwd 沙箱（`_resolve_within_root` → `SecurityError`）、`read-only`、`--allowedTools` 白名单透传、`--append-system-prompt`（有 `system` 时）。
   - hermes：`mock=True` 路径；真实路径的 URL/header/body 构造、`session_key` 头、`expect: json` 解析。
   - script：`handlers/<entry>.py::<entry>` 加载与调用。
   发现真实缺口才补；不要为"显得有产出"而重写已工作的逻辑。
2. **新建 `src/ticket_autopilot/engine/tests/test_drivers.py`**，包含：
   - 对 **每个** driver 的**直接单元测**（调用真实 `*_call`，用 mock 隔离 I/O）：
     - llm：用 `unittest.mock.patch('ticket_autopilot.engine.drivers.urllib.request.urlopen')` 返回假响应，断言解析出的文本/JSON 正确；缺 env 时抛 `RuntimeError`。
     - cli：`mock.patch` `subprocess.run`，断言构造的命令行含 `--permission-mode read-only`、`--allowedTools`、`--cwd`；cwd 落在 `sandbox` 外时断言抛 `SecurityError`（**不 spawn**）；cwd 在内时走 mock subprocess 返回成功。
     - hermes：`mock=True` 返回标记 dict；真实路径用 spy 断言 engine 把 `driver: hermes` 路由到 `hermes_call` 且传入 `(agent, inputs, node)`。
     - script：放一个**无副作用**的 fixture handler 到 `engine/handlers/`（如 `_test_echo.py` 含 `def _test_echo(**inputs): return inputs`），断言 `script_call` 返回其输出。
   - **至少一条 mock YAML 端到端驱动**：加载现有 `workflows/ticket-pipeline.yaml`（或内联极简 workflow），以 `mock=True` 跑 `Engine.run`，断言某个 driver 节点产出了 output（证明分发/路由对每类 driver 都通）。
3. **统一接口契约显式化**（满足 "统一接口"）：推荐引入一个 `Driver` 协议/注册表（如 `Driver.run(agent, inputs, node, ctx) -> object`，`ctx` 携带 `engine_root`/`mock`），并在 `engine/README.md`（或新增 `engine/drivers.md`）写明：每个 driver 的 env 变量、YAML `agents.<name>` 字段、返回形态、hermes 的 `mock` 开关、engine 分发约定，以及"未知 driver 抛 `WorkflowError`"的契约。若选择只文档化而不重构，须把当前 4 个签名 + 分发契约完整、准确地写出来（不得有歧义/虚构）。
4. **清理死代码（安全可选）**：`engine.py` 第 184–185 行有重复的 `raise WorkflowError(f"unknown driver: {driver}")`，删掉其中一行；并补一条"未知 driver → `WorkflowError`"的单测（或在文档里声明该行为）。

### Out of scope（严禁做）
- **不要实现新的安全护栏逻辑**（cli 沙箱/只读/白名单已存在且属于 **AIO-9 安全护栏** 票）。本票只**测试/保留**现有护栏，不得删改其语义；护栏功能增强交给 AIO-9。
- **不要新建平台 / 重写 `engine.py` 运行逻辑 / 引入新的编排框架**。
- **不要碰** `connectors/`（AIO-8）、`close_ticket` 对 Plane 的真实写入、生产密钥、数据库。
- **不要新增重依赖**到 `pyproject.toml`（现有 `dependencies = []`）；测试只允许 stdlib + 已有 PyYAML + pytest（pytest 跑 unittest 即可，不强制装包）。
- 真实 run 所需的 `XY_LLM_*` / `claude` CLI / Hermes gateway 不在本票范围（测试全部 mock）。

---

## 3. 验收标准（Acceptance Criteria，逐条 Pass/Fail）

- **AC-1｜每 driver 单测齐全**：`test_drivers.py` 含对 llm / cli / hermes / script **各自独立**的直接单元测，全部走 mock I/O（不触网、不 spawn 真实 CLI、不调用真实 handler 副作用）。
- **AC-2｜mock YAML 端到端驱动**：至少一条测试以 `mock=True` 加载 workflow 并 `Engine.run`，断言某 driver 节点产出 output（证明分发路由通）。
- **AC-3｜统一接口契约可核验**：`engine/README.md` 或 `engine/drivers.md` 显式写出 4 个 driver 的 env / YAML 字段 / 返回形态 / hermes `mock` 开关 / 未知 driver 报错契约，且与 `drivers.py` 实际实现一致（grep 可核验）。
- **AC-4｜无回归**：`test_engine.py` 仍全绿；cli 沙箱护栏（`SecurityError` on out-of-root cwd）**保持 intact** 且有测覆盖。
- **AC-5｜scope 纪律**：无新增护栏逻辑、无新平台/编排、无新依赖；engine 分发（`_run_node`）仍工作。
- **AC-6｜死代码清理（可选但鼓励）**：`engine.py:184-185` 重复 `raise` 去重；并补"未知 driver → `WorkflowError`"测试/文档。

---

## 4. 验证方式（Verification，确定性门禁）

```bash
cd /Users/hzuo/Documents/code/AI-Operations

# 主门禁（pytest 已装，可直接跑 unittest.TestCase）
PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/test_drivers.py -v

# 全量回归（含现有 test_engine.py 必须仍绿）
PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -v

# 若环境无 pytest，回退：
PYTHONPATH=src python -m unittest discover -s src/ticket_autopilot/engine/tests -v
```

- Pass = 上述命令全绿，且 `test_drivers.py` 满足 AC-1/AC-2。
- 人工/脚本核验：`grep -rn "SecurityError" src/ticket_autopilot/engine/drivers.py` 仍存在（护栏未被删）；`grep -n "unknown driver" src/ticket_autopilot/engine/engine.py` 仅剩一行（若做了 AC-6）。

---

## 5. 依赖（Dependencies）

- 前置：**#2「定义并接通闭环工单工作流」**（已落地，`AGENTS.md`/`IDEA.md` 为闭环定义来源）——本票无需再实现闭环，直接在现有 Engine 上工作。
- 参考（真实存在，必读）：
  - `src/ticket_autopilot/engine/drivers.py`（4 driver 实现）
  - `src/ticket_autopilot/engine/engine.py`（分发：`_run_node`、mock 处理、`SecurityError` 重复 raise 在第 184–185 行）
  - `src/ticket_autopilot/engine/README.md`（driver/护栏/hermes 文档）
  - `src/ticket_autopilot/engine/tests/test_engine.py`（现有 7 测，含 hermes mock 与 cli 护栏，作为风格范本）
  - `src/ticket_autopilot/workflows/ticket-pipeline.yaml` 与 `ticket-pipeline-hermes.yaml`
  - `src/ticket_autopilot/engine/handlers/close_ticket.py`（script driver 现有用法范本）
- ⚠️ **护栏边界**：cli 沙箱逻辑在 `drivers.py`，与 **AIO-9 安全护栏** 票重叠。本票只测/留，不增强；AIO-9 负责增强。

---

## 6. Definition of Done

- [ ] 4 个 driver 校验/补齐完成，实现与文档契约一致
- [ ] `src/ticket_autopilot/engine/tests/test_drivers.py` 存在且满足 AC-1 / AC-2
- [ ] 统一接口契约在文档中显式可核验（AC-3）
- [ ] 全量测试仍绿、cli 护栏 intact（AC-4）
- [ ] 无 scope 越界、无新依赖（AC-5）
- [ ] （鼓励） dead-code 清理 + 未知 driver 测试（AC-6）

---

## 7. 风险与回滚（Risk & Rollback）

- 风险：重构统一接口时破坏 engine 分发；误删 cli 护栏语义。
- 回滚：生产代码改动，`git revert` 对应提交即可；测试为 mock，不影响运行态。

---

## 8. 人工点位（Human touchpoints）

- **Trigger**：PM 将本票置 `In Progress` 即启动（唯一需要的人工启动动作）。
- **Gate**：PR review（本票产出为代码+测试+文档，需人 review 才合并）。
- **Escalation**：3 次失败重跑后升级给 PM。

---

## 9. 硬性约束（来自 AGENTS.md / IDEA.md，违反即 BLOCKED）

- **复用优先**：4 driver 已实现，校验/收口为主，不为"产出感"重写。
- **只认证据不认自述**：每个 AC 必须可被实际执行/核验（pytest 绿 + grep 证据）。
- **护栏不越权**：不实现新护栏逻辑（属 AIO-9）；现有 cli 沙箱必须保留。
- **不建新平台、不自动 merge、不碰生产密钥**。
- 任一确定性失败只标 `BLOCKED`，绝不标成功。

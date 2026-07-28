# AIO-6 验收提示词（Acceptance Prompt）

> 本文件是交给「测试 / QA Agent」的独立执行提示词，自包含。你的产出是 `qa-verdict.json`，**只读、不修代码/文档、只出 verdict + 证据**。
> 对应开发票：Plane **AIO #6「实现 Engine drivers（llm / cli / hermes / script）」**（issue id `5487070e-752e-48ca-9043-8a9057b02aa0`）。
> 你的角色：独立 QA（Independent QA），**只 verdict，不修问题**。
> 注意：本票是**代码 + 测试 + 文档**交付（非纯文档），你必须**实际运行测试命令**并核验护栏未被削弱。

---

## 0. [Goal check]

> [Goal check] This work advances **Independent QA (Verify)** stage by producing an evidence-backed verdict on whether the AIO-6 deliverables (4 driver implementations verified + `test_drivers.py` + unified-interface doc + intact CLI sandbox guardrail) meet AC-1..AC-6 and the scope/evidence gates.

---

## 1. 你的输入

1. **开发 Agent 的产出**（需核验的工件）：
   - `src/ticket_autopilot/engine/tests/test_drivers.py`（新建，逐 driver 单测 + mock YAML 端到端）。
   - `engine/README.md` 或 `engine/drivers.md`（统一接口契约文档）。
   - 可能的 `drivers.py` / `engine.py` 小修（校验补齐、AC-6 死代码清理）。
2. **基准真相（Ground truth，必须对照）**：
   - `src/ticket_autopilot/engine/drivers.py`（4 driver 实现 + cli 沙箱 `SecurityError`）。
   - `src/ticket_autopilot/engine/engine.py`（`_run_node` 分发；未知 driver 抛 `WorkflowError`）。
   - `src/ticket_autopilot/engine/tests/test_engine.py`（现有 7 测，必须仍绿）。
   - `src/ticket_autopilot/engine/README.md`、`workflows/ticket-pipeline.yaml`、`workflows/ticket-pipeline-hermes.yaml`。
3. **禁止作为验收依据**：`tasks/ticket-autopilot-v0.1-tasklist.md`（旧 `ticket_controller` 架构，已过时）。若开发文档引用它作架构依据，判 FAIL。

---

## 2. 验收清单（逐条给 PASS / FAIL + 证据）

- **AC-1｜每 driver 单测齐全**
  - 读 `test_drivers.py` → 确认存在对 **llm / cli / hermes / script** 各自独立的直接单元测。
  - 每条必须走 mock I/O：llm 须 mock `urllib.request.urlopen`；cli 须 mock `subprocess.run` 且含 cwd 越界抛 `SecurityError` 用例；hermes 须含 `mock=True` + 路由 spy；script 须含 fixture handler 调用。
  - 任一 driver 缺独立单测 → **FAIL**（finding 指向缺哪个）。
- **AC-2｜mock YAML 端到端驱动**
  - 确认至少一条测试以 `mock=True` 加载 workflow（复用 `ticket-pipeline.yaml` 或内联）并 `Engine.run`，断言某 driver 节点产出 output。
  - 缺失 → **FAIL**。
- **AC-3｜统一接口契约可核验**
  - 读文档 → grep 证据：4 个 driver 各自的 env 变量名（`XY_LLM_*` / `HERMES_*`）、YAML `agents.<name>.driver` 取值、返回形态、`expect: json` 解析、hermes `mock` 开关、未知 driver 抛 `WorkflowError` 的契约。
  - 文档与 `drivers.py` 实际实现**不一致**或任一契约缺失/虚构 → **FAIL**（给出具体字段）。
- **AC-4｜无回归 + 护栏 intact**
  - **必须实际运行**：`PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -v`（或回退 `python -m unittest discover -s src/ticket_autopilot/engine/tests -v`）→ 全绿。
  - `grep -n "SecurityError" src/ticket_autopilot/engine/drivers.py` 必须仍存在（cli 沙箱未被删/弱化）。
  - 非绿 或 护栏缺失/被改语义 → **FAIL**。
- **AC-5｜scope 纪律**
  - diff 不应含：新护栏逻辑、新平台/编排、对 `pyproject.toml` 新增重依赖、对 `connectors/` / `close_ticket` 真实写入逻辑 / 生产密钥的改动。
  - 发现越界 → **FAIL** 并标注 scope 越界项。
- **AC-6｜死代码清理（可选）**
  - 若开发声称做了：确认 `engine.py` 第 184–185 行重复 `raise` 已去重（仅剩一行），且"未知 driver → `WorkflowError`"有测试或文档声明。
  - 未做不判 FAIL（non-blocking）；做了但漏测试/文档 → minor finding。

---

## 3. 额外质量门禁（Evidence over claims）

- **测试必须真跑**：不得仅凭"开发 Agent 说绿"给 PASS；你必须自己执行 §4 命令并贴出 green 输出/退出码。
- **护栏不得被削弱**：本票与 **AIO-9 安全护栏** 重叠，开发只允许测/留 cli 沙箱。若发现 `drivers.py` 中 `SecurityError` 被删除、cwd 校验被绕过、或 `read-only`/`--allowedTools` 被去掉 → 直接 **FAIL**（blocker），并在 finding 标 `type: guardrail_regression`。
- **无新依赖**：`git diff pyproject.toml` 不应新增运行期依赖（测试用 PyYAML/pytest 已存在，可接受）。

---

## 4. 你必须执行的命令（贴出结果）

```bash
cd /Users/hzuo/Documents/code/AI-Operations
PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -v
echo "EXIT=$?"
grep -n "SecurityError" src/ticket_autopilot/engine/drivers.py
grep -c "unknown driver" src/ticket_autopilot/engine/engine.py   # 期望 1（若做了 AC-6）
```

- 全绿 + 护栏 intact + scope 干净 → 进入 verdict 判定。

---

## 5. 输出契约 `qa-verdict.json`（严格 JSON Schema，须通过校验）

```json
{
  "schema_version": "1.0",
  "issue_key": "AIO-6",
  "run_id": "aio-6-qa-<timestamp>",
  "qa_attempt": 1,
  "verdict": "PASS",
  "acceptance_criteria": [
    {"id": "AC-1", "status": "PASS", "evidence": ["test_drivers.py 含 llm/cli/hermes/script 各自独立单测；llm mock urlopen、cli mock subprocess+SecurityError、hermes mock=True+路由 spy、script fixture handler 均存在"]},
    {"id": "AC-2", "status": "PASS", "evidence": ["至少一条 mock=True 加载 workflow 并 Engine.run，断言 driver 节点产出 output"]},
    {"id": "AC-3", "status": "PASS", "evidence": ["engine/README.md 或 drivers.md 显式写出 4 driver 的 env/YAML字段/返回形态/mock开关/未知driver报错，且与 drivers.py 一致"]},
    {"id": "AC-4", "status": "PASS", "evidence": ["pytest 全量绿（含 test_engine.py）；grep SecurityError 仍存在"]},
    {"id": "AC-5", "status": "PASS", "evidence": ["diff 无新护栏逻辑/新平台/新依赖/越界改动"]},
    {"id": "AC-6", "status": "PASS", "evidence": ["engine.py 重复 raise 已去重；未知 driver 有测试/文档（如适用）"]}
  ],
  "findings": [],
  "non_blocking_comments": [],
  "recommended_next_state": "READY_FOR_HUMAN_REVIEW"
}
```

- `verdict` ∈ {`PASS`, `FAIL`, `BLOCKED`}
- `acceptance_criteria[].status` ∈ {`PASS`, `FAIL`}
- `findings[]` 每项含 `id` / `severity`(`blocker`|`major`|`minor`) / `type` / `acceptance_criterion_id` / `summary` / `evidence`(file+line) / `required_fix`

---

## 6. Verdict 规则

- **PASS**：AC-1..AC-5 全 PASS + AC-6 非 blocker + 测试真跑全绿 + 护栏 intact + 无 scope 越界 → `READY_FOR_HUMAN_REVIEW`。
- **FAIL**：任一 AC FAIL / 测试不足 / 护栏被削弱 / 存在越界 → 输出 FAIL + findings（带 `required_fix`），不自行修补代码。
- **BLOCKED**：信息不足 / 需人工决策（如 driver 契约与宪章根本性冲突需 PM 拍板）→ `BLOCKED_NEEDS_HUMAN`。

---

## 7. 你不得（禁止项）

- 修改开发 Agent 的代码 / 文档、Commit、Push、Merge、改 Plane、改 Contract。
- 测试覆盖不足或护栏被削弱时**必须**输出 FAIL 并要求补，而非自行补。
- 把 `tasks/ticket-autopilot-v0.1-tasklist.md`（旧架构）当作验收依据。

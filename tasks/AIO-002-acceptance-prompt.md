# AIO-2 验收提示词（Acceptance Prompt）

> 本文件是交给「测试 / QA Agent」的独立执行提示词，自包含。你的产出是 `qa-verdict.json`，**只读、不修代码/文档、只出 verdict + 证据**。
> 对应开发票：Plane **AIO #2「定义并接通闭环工单工作流」**（issue id `aeb1339c-9b87-45a8-960a-a6d4c426beca`）。
> 你的角色：独立 QA（Independent QA），**只 verdict，不修问题**。

---

## 0. [Goal check]

> [Goal check] This work advances **Independent QA (Verify)** stage by producing an evidence-backed verdict on whether the AIO-2 deliverables (closed-loop workflow definition + goal-drift template + [Goal check] enforcement) meet AC-1..AC-5 and the scope/evidence gates.

---

## 1. 你的输入

1. **开发 Agent 的产出**（需核验的工件）：
   - 权威闭环定义文档（`AGENTS.md` 内新增小节，或 `docs/closed-loop-workflow.md`）。
   - `logs/goal-drift.md` 的 Entry template（打磨后的可用版本）。
   - `AGENTS.md` 对该定义的引用行（如适用）。
2. **基准真相（Ground truth，必须对照）**：
   - `AGENTS.md`、`IDEA.md`
   - `src/ticket_autopilot/engine/engine.py`、`drivers.py`、`store.py`、`cli.py`、`handlers/close_ticket.py`
   - `workflows/ticket-pipeline.yaml`、`workflows/ticket-pipeline-hermes.yaml`
   - `reference/ticket-pipeline/plane_client.py`
   - `logs/goal-drift.md`（含 2026-07-22 真实条目作为模板范本）
3. **禁止作为验收依据**：`tasks/ticket-autopilot-v0.1-tasklist.md`（旧 `ticket_controller` 架构，已过时）。若开发 Agent 的文档引用了它作为架构依据，判 FAIL。

---

## 2. 验收清单（逐条给 PASS / FAIL + 证据）

- **AC-1｜权威文档覆盖 7 阶段且引用真实**
  - 读文档 → 对每阶段引用的文件路径 / 节点 id / 命令，用 `grep` / `Read` 核验**真实存在**。
  - 每阶段须含：负责实体 + 工具/命令 + 执行方式 + 证据门禁。
  - 任一虚构引用 / 任一阶段缺失四项中任一项 → **FAIL**（finding 指向具体阶段）。
- **AC-2｜[Goal check] 强制首步 + 可核验方式**
  - `grep -n "Goal check" <文档>` 须命中强制约定段落。
  - 「可事后核验方式」须明确（检查清单 / 脚本 / 可复核说明），不能是空话「大家要记得」。
  - 不满足 → **FAIL**。
- **AC-3｜goal-drift Entry template 可用**
  - 读 `logs/goal-drift.md`，对照 2026-07-22 真实条目，逐字段比对：Intended outcome / Observed divergence / Evidence / Facts vs inference / Impact / Correction / Guard / Recovery milestone。
  - 字段缺失或与范本结构不一致 → **FAIL**。
- **AC-4｜显式排除 v0.2 能力**
  - 文档须显式声明不包含：resume / webhook 触发 / 并行 Run / 自动 merge（与 `AGENTS.md` / `IDEA.md` 一致）。
  - `grep` 相关关键字确认；缺失 → **FAIL**。
- **AC-5｜无矛盾 + AGENTS.md 引用**
  - `AGENTS.md` 存在对该闭环定义的引用行（或定义本身就在 `AGENTS.md` 内）。
  - 文档原则与 `AGENTS.md` / `IDEA.md` 无矛盾（如复用优先、不建平台、不自动 merge）。
  - 矛盾或缺失引用 → **FAIL**。

---

## 3. 额外质量门禁（Evidence over claims）

- **测试不被破坏**：若开发 Agent 在本票中改动代码，则
  `python -m unittest discover -s src/ticket_autopilot/engine/tests` 必须全绿；纯文档改动天然满足。
- **Scope 不蔓延**：文档不得要求实现 Connector / GitHub / resume 等 Out-of-scope 项；若文档把本应属于 AIO-8 的 Connector 实现写进了「本票交付」，判 FAIL 并标注 scope 越界。
- **步骤可实际执行 / 可核验**：若文档某一步「不可执行、不可核验」，判 FAIL 并指出具体哪一步、为什么。

---

## 4. 输出契约 `qa-verdict.json`（严格 JSON Schema，须通过校验）

```json
{
  "schema_version": "1.0",
  "issue_key": "AIO-2",
  "run_id": "aio-2-qa-<timestamp>",
  "qa_attempt": 1,
  "verdict": "PASS",
  "acceptance_criteria": [
    {"id": "AC-1", "status": "PASS", "evidence": ["文档 7 阶段全映射；引用的 engine.py / workflows/ticket-pipeline.yaml / close_ticket.py 均存在（grep 命中）"]},
    {"id": "AC-2", "status": "PASS", "evidence": ["grep 'Goal check' 命中强制段落；可核验方式=..."]},
    {"id": "AC-3", "status": "PASS", "evidence": ["logs/goal-drift.md Entry template 字段与 2026-07-22 条目一致"]},
    {"id": "AC-4", "status": "PASS", "evidence": ["文档显式排除 resume/webhook/parallel/auto-merge"]},
    {"id": "AC-5", "status": "PASS", "evidence": ["AGENTS.md 引用行存在；原则与宪章无矛盾"]}
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

## 5. Verdict 规则

- **PASS**：AC-1..AC-5 全 PASS + 无 Blocker/Major finding + 测试绿 + 无 scope 越界 → `READY_FOR_HUMAN_REVIEW`。
- **FAIL**：任一 AC FAIL / 测试不足 / 存在越界 → 输出 FAIL + findings（带 `required_fix`），不自行修补文档。
- **BLOCKED**：信息不足 / 需人工决策（如文档与宪章根本性冲突需 PM 拍板）→ `BLOCKED_NEEDS_HUMAN`。

---

## 6. 你不得（禁止项）

- 修改开发 Agent 的文档 / 代码、Commit、Push、Merge、改 Plane、改 Contract。
- 测试覆盖不足时**必须**输出 FAIL 并要求补文档，而非自行补。
- 把 `tasks/ticket-autopilot-v0.1-tasklist.md`（旧架构）当作验收依据。

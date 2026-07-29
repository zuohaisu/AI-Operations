# AIO-1 验收提示词（Acceptance Prompt）

> 本文件是交给「测试 / QA Agent」的独立执行提示词，自包含。你的产出是 `qa-verdict.json`，**只读、不修代码 / 文档、只出 verdict + 证据**。
> 对应开发票：Plane **AIO #1「复用优先能力审计」**（issue id `4b1d03a5-be67-462b-9c4e-f2926126ab0c`）。
> 你的角色：独立 QA（Independent QA），**只 verdict，不修问题**。

---

## 0. [Goal check]

> [Goal check] This work advances **Independent QA (Verify)** stage by producing an evidence-backed verdict on whether the AIO-1 deliverable (`research/capability-audit.md`) meets AC-1..AC-6 and the scope/evidence gates (every claimed capability is verified, no fabrication, reuse-first honored).

---

## 1. 你的输入

1. **开发 Agent 的产出**（需核验的工件）：`research/capability-audit.md`。
2. **基准真相（Ground truth，必须对照）**：
   - `AGENTS.md`、`IDEA.md`
   - `src/ticket_autopilot/engine/engine.py`、`drivers.py`、`cli.py`、`handlers/close_ticket.py`
   - `workflows/ticket-pipeline.yaml`、`workflows/ticket-pipeline-hermes.yaml`
   - `reference/ticket-pipeline/plane_client.py`
   - `engine/tests/test_engine.py`
   - 已连接 MCP 能力边界（Plane / Linear / agent-mail，可在只读前提下探测）
3. **禁止作为验收依据**：`tasks/ticket-autopilot-v0.1-tasklist.md`（旧 `ticket_controller` 架构，已过时）。若开发 Agent 的文档以它为架构依据断言具体工具 / 文件，判 FAIL。

---

## 2. 验收清单（逐条给 PASS / FAIL + 证据）

- **AC-1｜7 阶段 + 2 横切全覆盖且三列齐全**
  - 读文档 → 确认 7 阶段（工单接入与契约 / 计划 Plan / 执行开发 Execute / 确定性验证与独立 QA / 有界修复循环 / PR 与 CI 证据 / 工单状态与结果）+ 2 横切（人工 Review 安全门 / 安全边界）均出现。
  - 每阶段须含「已有能力 + 缺口 + 最小胶水」三列，无空 / TBD。
  - 任一缺失 → **FAIL**（finding 指向具体阶段）。

- **AC-2｜每条已有能力经实际核验**
  - 对文档中每条「已有能力」，核验其引用的文件 / 工具 / 命令**真实存在**（`grep` / `Read` / 运行只读命令）。
  - 文档须标注核验方式；出现「应可用 / 应该能做」式无证据断言 → **FAIL**。
  - 发现虚构引用（文档 claim 但仓库不存在）→ **FAIL**。

- **AC-3｜明确「不新建平台」范围**
  - 文档须给出哪些阶段可由现有能力闭合或只需薄胶水，与 IDEA.md 复用优先一致。
  - 缺失 → **FAIL**。

- **AC-4｜已知坑清单 + 最小胶水**
  - 文档须列出已知坑（至少含：plane_client PROJECT_ID 错位、MCP 403 UA、Verifier≠Codex QA、PR 未实现、CLI stub、connectors/services/schemas 空脚手架），每条给最小胶水建议。
  - 缺任一项或只列坑不给建议 → **FAIL**。

- **AC-5｜纯审计 + 无矛盾**
  - 文档不要求实现代码（无新增 `src/` 业务代码指示）；原则与 AGENTS.md / IDEA.md 无矛盾（复用优先、不建平台、不自动 merge、不碰生产）。
  - 矛盾或越界要求实现 → **FAIL**。

- **AC-6｜下一步优先级**
  - 文档给出「最小胶水优先级」建议，可被后续票（AIO-2..AIO-9）直接引用。
  - 缺失 → **FAIL**（severity=major）。

---

## 3. 额外质量门禁（Evidence over claims）

- **测试不被破坏**：若开发 Agent 在本票中改动代码，则
  `python -m unittest discover -s src/ticket_autopilot/engine/tests` 必须全绿；纯文档改动天然满足。
- **Scope 不蔓延**：文档不得要求实现 Connector / GitHub PR / Codex QA / CLI 接线等 Out-of-scope 项；若文档把应属后续票的实现写进「本票交付」，判 FAIL 并标注 scope 越界。
- **断言可实际核验**：若文档某条能力断言不可核验，判 FAIL 并指出具体哪条、为什么。

---

## 4. 输出契约 `qa-verdict.json`（严格 JSON Schema，须通过校验）

```json
{
  "schema_version": "1.0",
  "issue_key": "AIO-1",
  "run_id": "aio-1-qa-<timestamp>",
  "qa_attempt": 1,
  "verdict": "PASS",
  "acceptance_criteria": [
    {"id": "AC-1", "status": "PASS", "evidence": ["文档 7 阶段 + 2 横切全覆盖；每阶段三列齐全，grep 命中各阶段名"]},
    {"id": "AC-2", "status": "PASS", "evidence": ["逐条能力引用路径已 grep/Read 核验真实存在；无「应可用」式空话"]},
    {"id": "AC-3", "status": "PASS", "evidence": ["文档给出不新建平台阶段清单，与 IDEA.md 复用优先一致"]},
    {"id": "AC-4", "status": "PASS", "evidence": ["已知坑 6 项齐列 + 各自最小胶水建议"]},
    {"id": "AC-5", "status": "PASS", "evidence": ["纯审计文档；原则与 AGENTS.md/IDEA.md 无矛盾"]},
    {"id": "AC-6", "status": "PASS", "evidence": ["给出最小胶水优先级，可被后续票引用"]}
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

- **PASS**：AC-1..AC-6 全 PASS + 无 Blocker/Major finding + 测试绿 + 无 scope 越界 → `READY_FOR_HUMAN_REVIEW`。
- **FAIL**：任一 AC FAIL / 测试不足 / 存在越界 → 输出 FAIL + findings（带 `required_fix`），不自行修补文档。
- **BLOCKED**：信息不足 / 需人工决策（如文档与宪章根本性冲突需 PM 拍板）→ `BLOCKED_NEEDS_HUMAN`。

---

## 6. 你不得（禁止项）

- 修改开发 Agent 的文档 / 代码、Commit、Push、Merge、改 Plane、改 Contract。
- 测试覆盖不足时**必须**输出 FAIL 并要求补文档，而非自行补。
- 把 `tasks/ticket-autopilot-v0.1-tasklist.md`（旧架构）当作验收依据。

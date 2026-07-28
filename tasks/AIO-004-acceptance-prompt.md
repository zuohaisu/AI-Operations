# AIO-4 验收提示词（Acceptance Prompt）

> 本文件是交给「测试 / QA Agent」的独立执行提示词，自包含。你的产出是 `qa-verdict.json`，**只读、不修代码/文档、只出 verdict + 证据**。
> 对应开发票：Plane **AIO #4「标准化 spec→issue 任务模板」**（issue id `6ce345cd-ff51-4160-8e81-d2a8d4443960`）。
> 你的角色：独立 QA（Independent QA），**只 verdict，不修问题**。
> 注意：本票是**文档 + 轻量工具（skill/脚本）**交付（非生产代码），但你必须**实际运行机制做 dry-run 自检**并核验「零范围蔓延」被强制。

---

## 0. [Goal check]

> [Goal check] This work advances **Independent QA (Verify)** stage by producing an evidence-backed verdict on whether the AIO-4 deliverables (the agent-ready ticket template locked as the single standard + a reusable spec→issue skill/process with enforced zero-scope-creep) meet AC-1..AC-6 and the scope/evidence gates.

---

## 1. 你的输入

1. **开发 Agent 的产出**（需核验的工件）：
   - 收紧后的 `specs/agent-ready-ticket-template.md`（唯一权威模板）。
   - 可复用机制：`AI-Operations/.workbuddy/skills/spec-to-plane-issue/SKILL.md`（skill 形态）或 `tooling/spec_to_issue.py` + 文档（脚本形态）。
   - 确定性自检：对内置示例 spec 跑 dry-run 并断言 9 字段 + 防范围蔓延规则。
2. **基准真相（Ground truth，必须对照）**：
   - `specs/agent-ready-ticket-template.md`（要收紧的模板）。
   - `docs/closed-loop-workflow.md`（引用该模板为「Ticket intake」契约）。
   - `AGENTS.md` / `IDEA.md`（宪章：复用优先、不建平台、不自动 merge）。
   - `reference/ticket-pipeline/plane_client.py`（REST 思路参考）。
   - `.workbuddy/memory/2026-07-27.md`（Plane REST gotchas 原文）。
3. **禁止作为验收依据**：`tasks/ticket-autopilot-v0.1-tasklist.md`（旧 `ticket_controller` 架构，已过时）。若开发文档引用它作模板/架构依据，判 FAIL。

---

## 2. 验收清单（逐条给 PASS / FAIL + 证据）

- **AC-1｜模板为唯一标准且收紧**
  - 读 `specs/agent-ready-ticket-template.md` → 含 9 字段 + 空白可填块 + Spec→Plane 流程 + worked example。
  - 且新增「拆分工单组规则」+「防范围蔓延核对清单」+「未满字段不得 In Progress 的强制门禁」。
  - `grep -n "Spec → Plane\|防范围蔓延\|工单组" specs/agent-ready-ticket-template.md` 须命中新增小节；任一缺失 → **FAIL**。
- **AC-2｜可复用机制存在且产出合规**
  - 确认 `AI-Operations/.workbuddy/skills/spec-to-plane-issue/SKILL.md` 或 `tooling/spec_to_issue.py` 存在且可调用/运行。
  - 机制对任意 spec 产出 1..N 个工单草稿，9 字段齐全、Out-of-scope 非空、AC 为可测 pass/fail、Verification 有具体命令。
  - 机制不存在或产出缺字段 → **FAIL**。
- **AC-3｜零范围蔓延被强制（非靠人自觉）**
  - 用一份**故意残缺的 spec**（缺 Scope boundary / AC 不可测 / Verification 空）跑机制 → 必须显式报错或标红，**不产出半截工单**。
  - 用一份**应拆未拆的 spec**（>1 独立可交付单元未拆）跑机制 → 必须提示拆分工单组。
  - 机制「静默放行」残缺 spec → **FAIL**（finding 标 `type: scope_creep_not_enforced`）。
- **AC-4｜确定性自检全绿（不触网）**
  - **必须实际运行**机制的 dry-run 自检（对内置示例 spec），断言产出满足 9 字段 + 防范围蔓延；命令退出码 0。
  - 自检依赖网络/真实 Plane → **FAIL**（本票自检必须 offline）。
  - 贴出 dry-run 输出 + 退出码。
- **AC-5｜无 scope 越界**
  - `git diff --stat` 不应含：`src/ticket_autopilot/engine/*`、`connectors/`、`reference/ticket-pipeline/plane_client.py` 的运行期改动；不应重建 Plane client / Engine。
  - 模板可 forward-reference `CONTRIBUTING.md` / `PULL_REQUEST_TEMPLATE.md`（归 AIO-3），但**不得实现**它们——若机制/文档实现了这两个文件 → **FAIL**（scope 越界到 AIO-3）。
  - 自检外不得触网写入真实 Plane（除非显式 `--apply` + 人工确认，本验收不要求）。
- **AC-6（可选 / 非阻塞）｜端到端演示**
  - 若开发做了 AC-6（真实创建 1 个 DRAFT 示例工单）：确认其为 `DRAFT` 标记、仅 1 个、且经人工确认。
  - 未做不判 FAIL（non-blocking）。

---

## 3. 额外质量门禁（Evidence over claims）

- **必须真跑自检**：不得仅凭"开发 Agent 说绿"给 PASS；你必须自己执行 dry-run 并贴出 green 输出/退出码。
- **防范围蔓延是核心卖点**：AC-3 的残缺 spec 测试是重点——若机制只是"建议"而非"拒绝"，判 FAIL。
- **不新建平台**：机制应是 skill/脚本 + 文档；若开发借机写了新编排框架 / 新 client → FAIL 并标注越界。

---

## 4. 你必须执行的命令（贴出结果）

```bash
cd /Users/hzuo/Documents/code/AI-Operations
# 文档收紧核验
grep -n "Spec → Plane\|防范围蔓延\|工单组" specs/agent-ready-ticket-template.md

# 机制 dry-run 自检（skill 形态：在 WorkBuddy 调用 spec-to-plane-issue 对内置示例 spec；
# 脚本形态：）
python tooling/spec_to_issue.py --dry-run --spec tests/fixtures/sample-spec.md --assert
echo "EXIT=$?"

# scope 越界核验
git diff --stat
```

- 自检全绿 + AC-1..AC-5 全 PASS + 无越界 + 残缺 spec 被拒 → 进入 verdict 判定。

---

## 5. 输出契约 `qa-verdict.json`（严格 JSON Schema，须通过校验）

```json
{
  "schema_version": "1.0",
  "issue_key": "AIO-4",
  "run_id": "aio-4-qa-<timestamp>",
  "qa_attempt": 1,
  "verdict": "PASS",
  "acceptance_criteria": [
    {"id": "AC-1", "status": "PASS", "evidence": ["specs/agent-ready-ticket-template.md 含 9 字段+空白块+Spec→Plane 流程+example；grep 命中拆组规则/防蔓延清单/强制门禁"]},
    {"id": "AC-2", "status": "PASS", "evidence": ["spec-to-plane-issue skill（或 tooling/spec_to_issue.py）存在可运行；产出 9 字段齐全、Out-of-scope 非空、AC 可测、Verification 有命令"]},
    {"id": "AC-3", "status": "PASS", "evidence": ["残缺 spec 被显式拒绝；应拆未拆 spec 提示拆组——零范围蔓延被强制"]},
    {"id": "AC-4", "status": "PASS", "evidence": ["dry-run 自检退出码 0；产出满足 9 字段+防蔓延；不依赖网络"]},
    {"id": "AC-5", "status": "PASS", "evidence": ["git diff 未动 Engine/Connector/plane_client；未实现 CONTRIBUTING/PR 模板（仅 forward-ref）；未触网"]},
    {"id": "AC-6", "status": "PASS", "evidence": ["（如适用）真实 DRAFT 示例工单仅 1 个且经人工确认"]}
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

- **PASS**：AC-1..AC-5 全 PASS + AC-6 非 blocker + 自检真跑全绿 + 无 scope 越界 → `READY_FOR_HUMAN_REVIEW`。
- **FAIL**：任一 AC FAIL / 自检不足 / 残缺 spec 被静默放行 / 存在越界 → 输出 FAIL + findings（带 `required_fix`），不自行修补。
- **BLOCKED**：信息不足 / 需人工决策（如模板与宪章根本性冲突需 PM 拍板）→ `BLOCKED_NEEDS_HUMAN`。

---

## 7. 你不得（禁止项）

- 修改开发 Agent 的代码 / 文档、Commit、Push、Merge、改 Plane、改 Contract。
- 测试覆盖不足或零范围蔓延未被强制时**必须**输出 FAIL 并要求补，而非自行补。
- 把 `tasks/ticket-autopilot-v0.1-tasklist.md`（旧架构）当作验收依据。

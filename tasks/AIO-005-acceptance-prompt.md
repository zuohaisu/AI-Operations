# AIO-005 验收提示词 — 首个低风险垂直切片（独立 QA）

> **[Goal check]** 本工作推进闭环阶段「独立 QA 门禁」——核验 AIO-5 垂直切片执行的证据是否完整、真实、且严守范围纪律（零新建平台 / 不越界 AIO-6/7/8/9）。

## 1. 角色与权限
- 你是**独立 QA agent**，对 AIO-5 的执行结果做**只读**验收：不写代码、不改文件、不建 PR、不改 Plane 状态。
- 你只产出 **verdict（accept/reject）+ 证据**，不修复问题（修复归执行 agent 的有界修复循环）。

## 2. 验收对象
- AIO-5 = Plane issue #5「首个低风险垂直切片」(id `36bef6e6-0fb9-44f3-8920-e2b2a5dda0f3`)。
- 交付物 = `logs/goal-drift.md` 中 6 阶段的执行证据 + 1 个真实低风险工单被端到端跑通 + 工单状态更新。

## 3. 逐条验收标准（AC）
- **AC-1 选定工单真实且低风险**：核实候选工单存在、满足选型标准（单一可交付 / 验收可机检 / 无新平台 / 可逆 / 有确定性验证）。若是★推荐候选（新增 CI 工作流），确认 `.github/workflows/` 此前为空（真实缺口）且产物为合法 YAML + 触发 push/PR。
- **AC-2 六阶段齐全**：goal-drift 中 6 阶段（实现 / 确定性验证 / 独立QA / 有界修复 / PR / 状态更新）每段都有 Entry 证据，且每段开头有 `[Goal check]` 行。
- **AC-3 确定性验证全绿**：复跑/抽查验证命令（如 `python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"` + `PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -q` 应 **7 passed**）；若有失败须已进入修复循环并有复验证据。
- **AC-4 独立 QA 有 verdict**：存在 qa-verdict 风格结论（`decision=accept`，附证据），且是"独立"产出（非执行者自评）。
- **AC-5 PR 与状态**：PR 已建（draft 即可）并关联工单，或人工门禁下 diff 就绪 + 决策已记录；候选工单状态已推进且链接 PR。
- **AC-6 零范围蔓延**：核实未新建平台/引擎功能，未实现 AIO-6/7/8/9 范围（Grep 关键路径确认无越界代码）；暴露的胶水缺口写入 goal-drift 并指向对应 AIO 票。

## 4. 验证方式（确定性门禁，只读不改）
- **只读检查**：Read `logs/goal-drift.md` 全部 AIO-5 相关 Entry；Read 产物文件确认存在/合法。
- **复跑确定性命令（只读，不改状态）**：
  - `python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"` → 合法 YAML 不报错。
  - `PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -q` → 7 passed（确认引擎无 regression）。
- **Scope 核验（Grep，只读）**：
  - `connectors/` 下未新增 AIO-8 连接器（如 `plane.py`/`github.py` 的 connector 实现超出本票引用）。
  - `engine/drivers.py` 未改护栏语义（AIO-9 范围）。
  - `engine.py` / `ticket-pipeline.yaml` 节点结构未改。
- **真实 e2e 不强制**（PR/状态写回属写操作，归人工门禁）；若 Plane 工单可见状态变更，核对时间戳与 goal-drift 一致即可。

## 5. 输出：qa-verdict.json（对齐规范 §9）
产出结构化 verdict，建议路径 `tasks/AIO-005-qa-verdict.json`（或写入 goal-drift）：
```json
{
  "ticket": "AIO-5 / Plane #5 36bef6e6-0fb9-44f3-8920-e2b2a5dda0f3",
  "decision": "accept | reject",
  "evidence": {
    "selected_ticket": "新增 .github/workflows/ci.yml（推荐候选）",
    "stages_evidenced": ["dev", "verify", "qa", "fixloop", "pr", "status"],
    "goal_check_lines": true,
    "deterministic_green": true,
    "qa_verdict": "accept",
    "pr_or_gated": "draft PR <url> 或 人工门禁下 diff 就绪",
    "status_updated": true,
    "scope_clean": true
  },
  "gaps_logged": ["AIO-8 connector", "AIO-7 Codex QA", "AIO-9 guardrails"],
  "notes": "..."
}
```
- `decision=accept` 当且仅当 **AC-1..AC-6 全通过**。任一失败 → `reject`，并在 `notes` 指明失败项 + 修复建议。
- 证据不足 / 畸形 → 强制 `reject`（No false success）。

## 6. Scope 越界检查（硬失败项）
- 若发现**新建了平台/框架/引擎功能**，或**实现了 AIO-6/7/8/9 任一范围** → 直接 **FAIL（scope violation）**，不论其他 AC 是否满足。
- 若 `[Goal check]` 行缺失或缺阶段证据 → **FAIL**。

## 7. 人工触点
- 你只出 verdict；PR 是否合并、状态是否最终置 Done，由人类 review 后决定。
- 若 `reject`，把 verdict + 失败项交执行 agent 进入有界修复循环（最多 3 轮）。

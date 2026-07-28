# AIO-8 验收提示词 — Ticket/PR 连接器（Plane → YAML → 关单/建 PR）

> 本文件是交给**独立 QA / 测试 agent** 的验收提示词。你只做验证与裁决。

## 0. 你的角色与硬约束
你是 AIO-8 的独立 QA agent。**只做验证与裁决，不修改任何产品代码、不提交、不建 PR、不 merge、不改 Plane/GitHub。** 你的唯一交付物是一份结构化 `qa-verdict.json`（可被机器校验）。

## 1. 验收对象
- Plane 工单 **AIO-8（#8）**：实现 Ticket/PR 连接器。
- 交付物：`src/ticket_autopilot/connectors/plane.py`、`connectors/github.py`（及对应测试）。

## 2. 验收标准（来自工单 Acceptance + Done + Risk）
- **AC-1**：给定 Plane 工单 ID，连接器能产出**合法 Engine YAML**（可被 Engine 加载 / 运行）。
- **AC-2**：闭环后（或等价演示下）工单状态更新为 Done + 评论，且 GitHub PR 在 feature branch 创建、非 main、待 review。
- **AC-安全**：PR 绝不 push/merge main；无生产密钥硬编码；尊重 Plane 限流；人工 review gate 存在。
- **AC-范围**：未实现 Engine/drivers/QA 本体，未实现 Linear。

## 3. 验证步骤（按顺序执行）

### 3.1 静态代码审查（只读）
- 连接器是否落在 `src/ticket_autopilot/connectors/` 下？
- 是否复用 `reference/ticket-pipeline/plane_client.py` 的鉴权 / 浏览器 UA / 限流写法，而非重复实现？
- 是否避免实现 Engine / drivers / QA？是否未触碰 Linear？
- `create_pr` 是否强制 `head != base`（feature branch），且**不**自动 merge？
- 密钥是否仅从 env 读取？有无硬编码？
- 是否处理 Plane 限流 / 错误（非静默）？

### 3.2 单元测试
- 运行 `pytest tests/`（聚焦 connector 测试）。
- 确认：issue→YAML 翻译有 mock 覆盖；YAML 结构合法性有断言（节点 / 边引用一致、必需字段齐全）。

### 3.3 YAML 合法性（直接满足 AC-1）
- 用一个（真实或样例）Plane 工单，调用 `build_workflow_yaml` 生成 YAML，落盘到临时文件。
- 将生成的 YAML 喂给：
  `python -m ticket_autopilot.engine run <生成的yaml> --mock --params '{"ticket_id":"<id>"}'`
  确认 Engine 能加载并跑完（mock 下无真实 Plane/GitHub 调用），即证明「合法 YAML」。
- 记录：生成 YAML 的路径、engine 运行结果（completed 节点列表、无 `not_completed` 卡住）。

### 3.4 端到端（gated）
- 若环境具备 Plane + GitHub 凭证（env：`PLANE_API_KEY`、GitHub token）：用一个真实低风险 Plane 工单跑通 `读 → YAML → 关单 → 建PR`，验证：PR 在 feature branch（非 main）、工单状态 Done + 评论。
- 若凭证缺失：**标记 NOT-RUN**，要求人工按 dev 提供的手动步骤执行，**不得**自行伪造 PASS。

### 3.5 安全复核
- 确认连接器遵守护栏约束（禁止 main push、人工 review）；无生产访问、无密钥入库。
- 检查 PR 创建路径：是否存在任何 `head == base` 或自动 merge 的分支。

## 4. Verdict 格式（必填，遵循 spec §9）
输出 `qa-verdict.json`：
```json
{
  "schema_version": "1.0",
  "issue_key": "AIO-8",
  "run_id": "aio-8-qa-<timestamp>",
  "qa_attempt": 1,
  "verdict": "PASS | FAIL | BLOCKED",
  "acceptance_criteria": [
    {"id": "AC-1", "status": "PASS|FAIL", "evidence": ["..."]},
    {"id": "AC-2", "status": "PASS|FAIL", "evidence": ["..."]},
    {"id": "AC-安全", "status": "PASS|FAIL", "evidence": ["..."]},
    {"id": "AC-范围", "status": "PASS|FAIL", "evidence": ["..."]}
  ],
  "findings": [
    {
      "id": "QA-001",
      "severity": "blocker|major|minor",
      "type": "IMPLEMENTATION_DEFECT|INSUFFICIENT_TEST_COVERAGE|SCOPE_VIOLATION|SECURITY",
      "acceptance_criterion_id": "AC-x",
      "summary": "...",
      "evidence": {"file": "...", "line": 0},
      "required_fix": "..."
    }
  ],
  "non_blocking_comments": [],
  "recommended_next_state": "PASS | FIXING | BLOCKED"
}
```
- 任一 AC 未满足或测试覆盖不足 → `verdict: FAIL`，并在 `findings` 指明 `required_fix`。
- 若凭证缺失导致无法验证 AC-2 → `verdict: BLOCKED`，`recommended_next_state: "BLOCKED"`，说明需人工 e2e。

## 5. 越权 / 范围蔓延判定
- 若发现 dev 实现了 Engine / drivers / QA / Linear → 直接 `FAIL`（范围违规），finding `type=SCOPE_VIOLATION`，`acceptance_criterion_id="AC-范围"`。

## 6. 报告
在你的回复中给出：verdict、每条 AC 的 evidence、关键文件路径、若 FAIL 的 `required_fix`。**不要修改代码。**

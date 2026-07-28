# AIO-9 验收提示词（Acceptance / QA Prompt）

> 由 PM agent 生成，交给**独立测试 / 验收 agent**。验收 agent 独立于开发 agent，只做验证与判定，**不修改任何文件**。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane）
- 工单：AIO-9「实现 Engine 安全护栏（CLI 沙箱 + 只读 + 白名单）」（issue `00a8fb04-240d-4e3e-b15e-0a1a4fbbc3ce`）
- 风险等级：R1｜类型：代码改动 **automated 验收**（pytest）
- ⚠️ 位置说明：AIO 任务在 **Plane**，不在 Linear。

## [Goal check]
本工作推进「独立验收（QA）」阶段，证据 = 逐条核对 AIO-9 的 5 条 AC，确认三道护栏在 Engine 层确定性成立且无范围蔓延 / 回归，产出 PASS/FAIL 判定 + 证据清单。

## 你的角色与权限
- 你是**独立验收 agent**，目标：判断 AIO-9 交付物是否满足验收标准。
- 你可以：读取仓库所有文件、运行**只读**检查命令（如 `pytest`、`grep`、读 diff）。
- 你**不可以**：修改代码 / 文档 / 测试、Commit、Push、Merge、建 PR、改工单、改验收标准。
- 若护栏不足或存在缺口，必须输出 **FAIL** 并列出具体缺口（不替开发 agent 补做）。

## 输入
- AIO-9 工单原文（见开发提示词或 Plane issue）
- 开发提示词中定义的 5 条 AC（AC-1 ~ AC-5）
- 待验收的 PR / 分支 diff（重点看 `engine/guardrails.py`（新）、`engine/drivers.py` 改动、`tests/test_guardrails.py`（新））

## 验收方法（证据优先）
逐条核对以下清单。每条必须给出**证据**（测试名 / grep 到的代码位置 / 命令 exit code），不得仅凭「看起来对」。

### AC-1 — 越权路径被拦截
- 证据：在测试中构造节点 `cwd` 落在 allowed roots 之外 → 断言抛 `SecurityError` 且 CLI 未被 spawn（可用 mock cli_call 或断言异常）。
- 判定：测试通过 + 代码确认 Engine 层先校验后 spawn = PASS；否则 FAIL。

### AC-2 — 写命令被拦截（重点）
- 证据：构造节点 `permission_mode: write` 且策略 `read_only=True` → 断言 `SecurityError`，且**代码里确实在 Engine 层拒绝**（grep 确认不是只把 `--permission-mode read-only` 透传了事）。
- 判定：测试通过 + 代码审阅确认有显式拒绝分支 = PASS；否则 FAIL。

### AC-3 — 白名单外工具被拒
- 证据：构造节点 `tools` 含白名单外工具 → 断言 `SecurityError`。
- 判定：测试通过 = PASS；否则 FAIL。

### AC-4 — 配置项可调
- 证据：确认 roots / read_only / whitelist 由配置驱动（非硬编码）；存在测试演示「放宽白名单 → 原本被拒的工具被放行」。
- 判定：配置代码 + 演示测试通过 = PASS；否则 FAIL。

### AC-5 — 回归
- 证据：确认 `engine/drivers.py` 仍可导入、既有 `ticket-pipeline.yaml` 的 `executor`（read-only + `[Read,Glob,Grep]` + sandbox）路径不被破坏、`pytest` 整体无回归。
- 判定：`pytest` 全绿 + 既有 workflow 可加载 = PASS；否则 FAIL。

## 附加检查（Scope 越界）
- 检查 diff 是否引入网络隔离、沙箱虚拟化、数据库迁移、生产访问。若越界 → FAIL（scope violation），并在 findings 标注 `type: SCOPE_VIOLATION`。
- 确认没有把凭证写进任何配置文件 / 没有新增对生产系统的访问 / 没有改 main 分支。
- 开发 agent 不得直推 main、不得 merge、不得改 Plane/Linear 之外的系统、不得碰生产密钥。若发现 → FAIL（`type: SECURITY_VIOLATION`）。

## 验证命令（只读，可运行）
```bash
pytest tests/test_guardrails.py   # 必须全绿
pytest                           # 仓库整体无回归
python -m ticket_autopilot.engine run --mock   # 确认无 import 回归
```
所有 Exit Code 必须为 0；任何非 0 即 FAIL。

## 产出（qa-verdict 风格）
输出一份结构化判定（建议下列字段）：
```
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-9
run_id: <本次验收标识>
acceptance_criteria:
  - id: AC-1 .. AC-5
    status: PASS/FAIL
    evidence: <测试名 / file:line / exit code>
findings:
  - id: QA-001
    severity: blocker|major|minor
    type: <INSUFFICIENT_TEST_COVERAGE | SCOPE_VIOLATION | SECURITY_VIOLATION | IMPLEMENTATION_DEFECT>
    summary: ...
    evidence: <file:line>
    required_fix: ...
scope_violation: bool
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```
- 全部 AC PASS 且无 blocker/major → `verdict: PASS`。
- 任一 AC FAIL 或存在 blocker/major → `verdict: FAIL`，并要求开发 agent **只修 findings**（窄范围，不扩大 scope）。
- 若对「写命令」判定口径无法判定 → `verdict: BLOCKED`（BLOCKED_NEEDS_HUMAN）。

## 禁止事项
- 不修改任何文件（含文档与测试）。
- 不自行补做缺失测试或护栏代码。
- 不放松 AC 标准以通过。
- 若 `tests/test_guardrails.py` 缺少任一 AC 的用例（尤其 AC-2 的 Engine 层拒绝分支），直接判 FAIL（type: `INSUFFICIENT_TEST_COVERAGE`）。

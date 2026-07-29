# AIO-10 验收提示词（Acceptance / QA Prompt）

> 交给独立 QA agent。只读验收，禁止修改文件、Commit、Push、建 PR 或改 Plane。

## 任务身份与目标
- 工单：AIO-10「实现 Plane 工单到 ticket-spec 的确定性契约门禁」
- Plane issue id：`d2974231-04b4-4f8b-b8ef-22aac2c3bf5b`
- 风险：R1｜类型：automated
- `[Goal check]`：推进「Independent QA」，证据 = 逐条验证契约映射、preflight 阻断、可追溯性与 Connector 复用，输出结构化 verdict。

## 验收前检查
1. 读 `AGENTS.md`、Plane 原票、开发提示词、待验收 diff。
2. 记录 `git status --short --branch`、base/head SHA、改动文件；确认范围主要在 schema、services、tests。
3. 不采信 Developer Summary 作为成功证据。

## AC 逐条验收
- AC-1：用完整 R0/R1 fixture 生成 ticket-spec；核对 schema 校验通过且字段来源可追溯。
- AC-2：逐个删除 Goal、Scope、Out-of-scope、AC、Verification、Repository；均须 `BLOCKED_REQUIREMENTS`，并以 mock 证明 Planner/Executor/QA 未调用。
- AC-3：manual verification、R2、R3 分别产生明确 Blocked；不得进入执行。
- AC-4：序列化往返后 schema_version、issue key、repository、AC IDs、required checks、constraints 不丢失。
- AC-5：审查实现是否复用 AIO-8 Plane Connector；若复制 HTTP/auth/rate-limit 逻辑则 FAIL。

## 必跑命令
```bash
python3 -m pytest tests/test_ticket_contract.py -q
python3 -m pytest -q
```
必须记录每条命令及 exit code。测试缺少“Agent 未调用”断言、只测 happy path 或全套回归非 0，均判 FAIL。

## 范围与安全检查
- 不得出现 Worktree、PR、Plane 状态写回、Linear intake、新编排器或 LLM 质量判断。
- 不得打印/写入凭证，不得触网修改真实 Plane。
- 发现 scope/security violation 时直接 FAIL，不替开发 agent 修复。

## 输出格式
```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-10
acceptance_criteria:
  - id: AC-1
    status: PASS | FAIL
    evidence: <command/test/file:line>
findings:
  - id: QA-001
    severity: blocker | major | minor
    type: IMPLEMENTATION_DEFECT | INSUFFICIENT_TEST_COVERAGE | SCOPE_VIOLATION | SECURITY_VIOLATION
    summary: <事实>
    required_fix: <最小修复>
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```
全部 AC PASS 且无 blocker/major 才能 PASS；证据或环境无法判断时 BLOCKED，不能降标。

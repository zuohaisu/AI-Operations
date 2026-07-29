# AIO-10 开发提示词（Developer Prompt）

> 交给开发 agent 执行。开始前必须读 `AGENTS.md`、`IDEA.md`、`docs/closed-loop-workflow.md`，并先输出 `[Goal check]`。不得自行扩大工单范围。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane workspace `hspace`）
- 工单：AIO-10「实现 Plane 工单到 ticket-spec 的确定性契约门禁」
- Plane issue id：`d2974231-04b4-4f8b-b8ef-22aac2c3bf5b`
- 优先级：high｜风险：R1｜验收：automated

## [Goal check]
本工作推进「Ticket intake / contract」阶段，证据 = Plane 工单可确定性生成并校验 `ticket-spec.json`，不合格工单在任何 Agent 调用前被阻断。

## 目标与现状
复用 AIO-8 已有 Plane Connector，把 Plane Issue 机械映射为可追溯、可校验的 ticket-spec。不得用 LLM 猜测缺失字段，也不得重建 Plane HTTP client。

## In scope
- 新增 `src/ticket_autopilot/schemas/ticket-spec.schema.json`。
- 在 `src/ticket_autopilot/services/` 实现映射、JSON Schema 子集校验和 R0/R1 preflight。
- 承重字段至少含 Goal、Scope、Out-of-scope、Risk Tier、AC、Verification、Repository、Required Checks、Constraints。
- 不合格输入输出机器可读的 `BLOCKED_REQUIREMENTS` 或 `BLOCKED_NEEDS_HUMAN`，且 Planner/Executor/QA 调用次数均为 0。
- 覆盖合法、缺字段、manual verification、R2/R3、取消工单测试夹具。

## Out of scope
- Worktree/Branch、开发执行、测试运行器、PR、Plane 状态写回。
- Linear/GitHub Issues intake；LLM 质量评审；新编排器或第二个 Plane client。

## 验收标准
- AC-1：完整 R0/R1 Plane 工单映射为 schema-valid `ticket-spec.json`，所有值可追溯。
- AC-2：缺 Goal/Scope/Out-of-scope/AC/Verification/Repository 时返回 `BLOCKED_REQUIREMENTS`，不调用 Agent。
- AC-3：manual verification 或 R2/R3 返回明确 Blocked，不进入开发。
- AC-4：序列化往返保持 schema_version、issue key、repository、AC IDs、checks、constraints。
- AC-5：复用 AIO-8 Connector，不改变其鉴权、限流路径。

## 确定性验证
```bash
python3 -m pytest tests/test_ticket_contract.py -q
```
通过条件：所有正反向场景全绿，测试明确断言非法工单不会调用任何 Agent。任何漏检或错误放行均为失败；两轮窄修复后仍失败则 `BLOCKED_NEEDS_HUMAN`。

## 依赖与完成定义
- 依赖 AIO-1、AIO-4、已完成的 AIO-8；产品依据为 `specs/Ticket Autopilot PRD.md`。
- schema、映射、校验、Blocked 分类和每条 AC 的自动化证据全部落地。
- 全套相关测试 exit code 0；独立 QA PASS；只创建待人工 Review/Merge 的 PR。

## 执行指引
1. 先检查现有 Connector、Engine 输入及测试布局，写最小设计，不另起平台。
2. 先定义版本化 ticket-spec schema，再实现纯映射/校验和 preflight。
3. 使用 mock/fixture 证明失败发生在 Agent spawn 前。
4. 运行确定性命令及相关回归测试，Commit message 含 `AIO-10`。
5. 输出 Developer Summary 与证据路径；开发 agent 不自行改 Plane、Merge 或推 main。

## 风险、回滚与人工点位
- 风险：过严导致误挡，过松导致无证据放行；字段无法无歧义映射时必须 Blocked。
- 回滚：仅 schema/service/tests，使用 `git revert`，保持既有 Connector 不变。
- Trigger：PM 将 AIO-10 移到 In Progress。
- Gate：人工 Review 字段边界与 Blocked 分类。
- Escalation：Risk、Repository 或 Verification 不能确定时返回 `BLOCKED_NEEDS_HUMAN`。

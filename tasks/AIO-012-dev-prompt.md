# AIO-12 开发提示词（Developer Prompt）

> 开发 agent 开始前读 `AGENTS.md`、`IDEA.md`、AIO-10/AIO-11 接口并输出 `[Goal check]`。

## 任务身份
- 工单：AIO-12「实现确定性开发验证与工程证据归档」
- Plane issue id：`dce4a1df-7d8f-4a5c-b6a0-f424a6fe1f6e`
- 优先级：high｜风险：R1｜验收：automated

## [Goal check]
本工作推进「Deterministic Verification」阶段，证据 = Controller 仅凭 Commit/Diff/Scope/命令 exit code 判定开发结果，并持久化可供独立 QA 消费的 evidence bundle。

## 核心原则
Developer Summary 只供人读，永远不参与成功判定。所有命令在 AIO-11 的 Worktree 中以显式 cwd、超时和可回读输出运行。

## In scope
- 在 `src/ticket_autopilot/services/` 实现 development verifier。
- 校验 Worktree、branch、base/head SHA、新 Commit、非空 Diff、冲突、commit message issue key。
- 执行 ticket-spec 的 automated/query verification、required_checks 与基础检查。
- 记录 command、cwd、stdout/stderr、exit code、开始/结束时间。
- 检查 `forbidden_paths`、`max_changed_files`；命中时 `BLOCKED_NEEDS_HUMAN`。
- 将 Git/test/scope 证据写入 Run artifacts，形成只读 evidence bundle。

## Out of scope
- LLM 运行/解释确定性检查；PR、真实 Plane/GitHub、生产检查、不可逆命令。
- QA schema、产品 CLI、CI Dashboard。

## 验收标准
- AC-1：无新 Commit → `BLOCKED_ENVIRONMENT`，GitHub Connector 未调用。
- AC-2：空 Diff、冲突、commit message 无 issue key → 明确失败并记录证据缺口。
- AC-3：每条 verification/check 在 Worktree 执行，保存真实 exit/stdout/stderr。
- AC-4：任一 required command 非 0 → 不产生 verified，不允许 PR。
- AC-5：全部 Git/Diff/Scope/commands 通过 → evidence bundle 可由 QA Connector 直接消费。
- AC-6：forbidden path 或超文件数 → `BLOCKED_NEEDS_HUMAN`，不得自动放行。

## 确定性验证
```bash
python3 -m pytest tests/test_development_verifier.py -q
```
测试只使用临时仓库和无副作用命令。无证据放行、失败命令后仍可建 PR、输出不落盘或 Scope 未拦截，均为 FAIL。

## 执行与完成定义
1. 先固定 evidence bundle 版本化契约和状态映射，再实现检查器。
2. 命令执行必须限制 cwd/timeout，并原样记录 exit/stdout/stderr；不得把模型总结当证据。
3. 为 6 条 AC 写 happy/negative tests，并跑相关回归。
4. Commit message 含 `AIO-12`，输出证据路径和 Developer Summary。
5. 独立 QA PASS、PR 待人工 Review/Merge；开发 agent 不改 Plane、不建 PR、不推 main。

## 依赖、风险与人工点位
- 依赖 AIO-10 ticket-spec、AIO-11 Run/Worktree/artifacts。
- 风险：命令越界/挂起；证据字段缺失导致 QA 误判。
- 回滚：`git revert` verifier/tests，不删 Run 外证据。
- Gate：人工 Review 命令边界、证据完整性、Blocked 分类。
- Escalation：check 涉及网络、生产、迁移、交互输入或不可逆操作时 `BLOCKED_NEEDS_HUMAN`。

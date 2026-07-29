# AIO-15 开发提示词（Developer Prompt / Real R0 Pilot）

> 这是首张真实 Pilot，不是普通手工开发任务。唯一合规启动方式是 PM 执行 `ticket-controller run AIO-15`；不得人工复制本提示词来替代 Controller 的 intake。

## 任务身份
- 工单：AIO-15「用闭环文档更新运行首张真实 R0 Pilot」
- Plane issue id：`c99bc58f-73b2-4e4c-a9e4-68081f54368d`
- 优先级：high｜风险：R0｜依赖：AIO-10～AIO-14 均 QA PASS 且已合并

## [Goal check]
本工作推进「Real ticket vertical slice」阶段，证据 = 一次 `ticket-controller run AIO-15` 自动产出 Run/Worktree/Commit/checks/独立 QA/Draft PR，并把 Plane 置 In Review。

## Pilot 纪律
- 此文件用于冻结意图与验收口径，不得作为人工旁路 Prompt。
- 任一步需要人工补 Prompt、造证据、放松护栏或改 Scope，立即 `BLOCKED_NEEDS_HUMAN`；保留失败事实。
- 成功终点是 Draft PR + Plane In Review，不是 auto-merge 或 Done。

## In scope
- PM 仅执行一次 `ticket-controller run AIO-15`。
- Developer 只更新 `docs/closed-loop-workflow.md`，清除 Connector/schema 未实现等陈旧断言，使其符合当前 Plane-first Engine/Connector/Guardrail 架构。
- Controller 自动产生 Run/Worktree/Branch、确定性检查、QA、Draft PR、Plane In Review。
- 保留 run_id、commit/diff、exit code、qa-verdict、PR URL、Plane state 证据。

## Out of scope
- 不改 `src/`、tests、PRD、历史 specs 或其他 prompts。
- 不手工建 branch/复制 Prompt/伪造 verdict/直接 Done。
- 不 auto-merge/deploy/访问生产。

## 验收标准
- AC-1：一次 run 命令完成 intake→develop→verify→QA→Draft PR→In Review，人工 Prompt 复制=0。
- AC-2：文档不再声称 Plane/GitHub/QA Connector 或 ticket-spec schema 不存在。
- AC-3：Diff 只含目标文档和预期 Run artifacts；无 `src/`/tests 产品改动。
- AC-4：QA verdict schema-valid PASS，逐 AC 有可核验证据。
- AC-5：有 feature branch、非空 Commit/Diff、Draft PR；Plane=In Review 而非 Done。
- AC-6：任一门禁失败则明确 Blocked，不报告 Pilot success。

## 确定性验证
```bash
python3 -c "from pathlib import Path; t=Path('docs/closed-loop-workflow.md').read_text(); assert 'connectors/plane.py' in t; assert 'connectors/github.py' in t; assert 'connectors/qa.py' in t; assert 'not yet present' not in t"
```
除此之外必须回读 Run artifacts、QA PASS、Draft PR 与 Plane In Review。任何证据缺失、范围越界、非 Draft PR、人工补跑 Agent 都为 FAIL/BLOCKED。

## 执行/回滚/人工点位
1. PM 确认 AIO-10～14 已合并且凭证 preflight 可通过，再将本票 In Progress。
2. 只执行唯一启动命令；后续全部由 Controller 驱动。
3. Pilot 失败时不手工修饰；cleanup 仅清本 Run disposable 本地资源并保留日志。
4. 人工只在 Draft PR Gate Review/Merge；Merge 后才允许既有自动化或人置 Done。
- 回滚：关闭 PR 或 `git revert` 文档变更，不改写 verdict/history。

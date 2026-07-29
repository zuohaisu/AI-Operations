# AIO-13 开发提示词（Developer Prompt）

> 开发 agent 开始前读 `AGENTS.md`、`IDEA.md`、`docs/closed-loop-workflow.md` 及 AIO-7～AIO-12 交付物，并输出 `[Goal check]`。

## 任务身份
- 工单：AIO-13「接通真实闭环工作流与 Plane/GitHub 状态语义」
- Plane issue id：`3e9e6450-4759-4a45-8e59-d6acb1545e7c`
- 优先级：high｜风险：R1｜验收：automated integration

## [Goal check]
本工作推进「Workflow orchestration」阶段，证据 = intake→plan→execute→verify→independent QA→Draft PR/Plane state 的真实顺序可测，且不存在 false success。

## In scope
- 扩展现有声明式 workflow，按 preflight → plan → execute → deterministic verify → QA → PR/status 顺序连接已有能力。
- QA 输入含原始 ticket-spec、base→head Diff、测试证据、run_id、qa_attempt。
- PASS：仅在确定性验证通过后创建 Draft PR，Plane → In Review，并附 PR/Run/Checks/QA 摘要。
- FAIL：默认最多两轮窄修复，只透传原始 findings；每轮完整重跑 verify + QA。
- BLOCKED/畸形 JSON/超时/缺证据：立即停止，Plane → Blocked，不当 FAIL 重试。
- 最小扩展既有 Plane/GitHub Connector；外部 I/O 全 mock 的集成测试验证调用顺序和幂等语义。

## Out of scope
- 产品 CLI、Web UI、auto-merge/deploy、Linear、并行/Resume。
- Execute/Verify 双备份、重写 Engine、第三套 Connector。
- 测试访问真实 Plane/GitHub/Agent。

## 验收标准
- AC-1：valid PASS + verified → Draft PR + Plane In Review + 完整摘要。
- AC-2：QA FAIL 且 attempt<2 → 只把原始 findings 给 Execute，再完整 verify/QA。
- AC-3：两轮 Fix 后第三次 FAIL → `BLOCKED_QA_EXHAUSTED`，不再 Execute/PR。
- AC-4：QA BLOCKED/坏 JSON/超时/缺证据 → 对应 Blocked，不走 FAIL retry。
- AC-5：deterministic verify 失败 → QA、PR、In Review 均不发生。
- AC-6：GitHub/Plane API 失败 → 保留 Run evidence，`BLOCKED_ENVIRONMENT`，不得 success。
- AC-7：任何成功路径均无 auto-merge、main push、Done-before-human-review。

## 确定性验证
```bash
python3 -m pytest tests/integration/test_ticket_pipeline.py -q
```
happy、one-fix、exhausted、QA BLOCKED、verify/GitHub/Plane failure、安全红线全部通过。任何假成功、错误重试、超过两轮、直接 Done 或调用顺序错误即 FAIL。

## 执行指引
1. 先画出现有节点与状态映射，复用 Engine/Connector，不另建 controller 平台。
2. 把 PASS/FAIL/BLOCKED 设为互斥结构化分支，副作用前做前置证据检查。
3. 外部写入支持可测试的顺序/失败语义；真实网络不进入测试。
4. 完成 AC-1～AC-7 集成测试及全套回归；Commit 含 `AIO-13`。
5. 输出 Developer Summary；不改真实 Plane、不自行建/合 PR、不推 main。

## 依赖、风险与人工点位
- 依赖已完成 AIO-7/8/9 及 PASS 的 AIO-10/11/12。
- 风险：状态/重试顺序错误造成假成功或重复副作用。
- 回滚：mock-first，代码通过 `git revert`；真实写仅在后续 Pilot 人工门禁下启用。
- Gate：人工 Review 状态机、两轮 Fix、幂等性、无 auto-merge。
- Escalation：承重顺序无法从 PRD 确定时 `BLOCKED_NEEDS_HUMAN`，不得自行改产品语义。

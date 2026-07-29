# AIO-13 验收提示词（Acceptance / QA Prompt）

> 独立 QA 只读验收。不得改 workflow/tests、触发真实 Plane/GitHub、建 PR 或修复问题。

## 任务身份与 Goal check
- 工单：AIO-13「接通真实闭环工作流与 Plane/GitHub 状态语义」
- Plane issue id：`3e9e6450-4759-4a45-8e59-d6acb1545e7c`
- `[Goal check]`：推进「Independent QA」，证据 = 验证三态路由、两轮修复上限、外部副作用顺序和 no-false-success。

## 验收前检查
- 读原票、开发提示词、workflow、AIO-7～AIO-12 接口和 diff。
- 记录 Git 状态与改动范围；确认全部外部 I/O 被 mock。
- 重点审查副作用顺序，不以 HTTP 200 或自然语言 summary 代替语义断言。

## AC 证据矩阵
- AC-1：PASS 仅在 deterministic verified 后建 Draft PR；Plane 为 In Review 且摘要完整。
- AC-2：第一次/第二次 FAIL 只透传原始 findings，随后完整 verify + QA。
- AC-3：第三次 FAIL 为 `BLOCKED_QA_EXHAUSTED`，没有额外 Execute/PR。
- AC-4：BLOCKED、malformed JSON、timeout、missing evidence 各自停止，不计 fix attempt。
- AC-5：verify failure 时 QA/PR/In Review 调用次数为 0。
- AC-6：GitHub 与 Plane 失败分别保留 evidence、返回 `BLOCKED_ENVIRONMENT`，无 success。
- AC-7：断言 auto-merge/main push/Done-before-review 全部为 0。

## 必跑命令
```bash
python3 -m pytest tests/integration/test_ticket_pipeline.py -q
python3 -m pytest -q
```
记录 exit code、关键测试和调用序列。缺任何承重失败场景或测试触网即 FAIL。

## Scope / security
- 不应出现产品 CLI/UI、Linear、并行/Resume、第二个 Engine、第三套 Connector。
- 不得有真实凭证、真实 Plane/GitHub/Agent 请求、auto-merge、main push、Done。

## Verdict
输出 AIO-13 的 `verdict`、AC-1～AC-7 状态/证据、按 severity 分类的 findings、scope/security violation、recommended next state。全部 AC PASS 且无 blocker/major 才 PASS；无法安全验证外部隔离时 BLOCKED。

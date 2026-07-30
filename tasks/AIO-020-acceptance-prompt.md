# AIO-20 验收提示词（Acceptance / QA Prompt）

> ⚡ **立即开始只读验收，不要询问意图或请求只读许可。** 真正 blocker 写入 verdict；不得修改事件、重试真实 Run、停止未知进程或用人工补数据美化 Timeline。

## 任务身份与 Goal check
- 工单：AIO-20「实现 Run Timeline、Hard Break 人工介入与完整页面追踪」
- Plane issue id：`fca986c3-6482-43e6-8a45-6767cb4c3bf6`
- `[Goal check]`：推进「Independent QA / evidence integrity」，证据 = 交叉核对页面、API、events/state、owned process 和视觉证据，确认无假进度、越界控制或 Secret 泄露。

## 验收准备
- 重跑 AIO-19 readiness；票状态不是能力证据。
- 读原票、Dev Prompt、事件 schema、所有生产者/消费者、Retry/Stop 所有权代码和 diff。
- 记录 base/head、ticket-owned files 与 pre-existing dirty paths；归因不清时 `BLOCKED_ATTRIBUTION`。
- 所有控制测试使用临时进程；不得操作用户真实服务/Run。

## AC 证据矩阵
- AC-1：逐事件比对 Timeline 与 artifacts；时间、stage、role、round、findings、changed files、SHA 均一致。
- AC-2：关闭页面后 owned worker 仍运行；重开后仅靠 persisted state/events 恢复。
- AC-3：Developer/QA/runtime Hard Break 分别呈现正确上下文，不映射成 QA FAIL/PASS；Repo Owner visual accept/override 显示 actor/action/time/reason，且原始 pending/fail 事件仍可追溯。
- AC-4：Retry 沿用 run_id、历史长度只增不减，并重新触发后续 checks/QA/Commit 门禁。
- AC-5：Stop 的目标等于 owned process group；foreign process call=0，artifacts 保留。
- AC-6：递归注入 Secret 到异常/事件/findings 后，API/HTML/DOM/log/raw artifact 均无完整值。

## 必跑命令
```bash
python3 -m pytest tests/test_web_run_tracking.py tests/integration/test_web_hard_break.py -q
python3 -m pytest -q
```

## 浏览器与视觉验收
- 记录 viewport、URL 和 running/FAIL/Hard Break/COMPLETED 四种截图或等价可复核证据。
- 检查长 finding、长路径、五轮 QA、错误原因不会遮挡操作；状态、角色、轮次和 Prompt source 不混淆。
- Retry/Stop/Finder 只在合法状态显示，禁用状态不能通过直接 API 绕过。
- 缺视觉证据且尚无人类结论时，UI 状态为 `HUMAN_VISUAL_REVIEW_PENDING`，不能 QA PASS，但不阻止 Draft PR。Owner accept/override 必须留下审计记录且不能改写历史 verdict。

## QA 权限与 Verdict
- 不得建议覆盖历史事件、跳过失败门禁或用另票修复本票强制 schema/reader 同步。
- 不以“函数被调用”证明正确；核对实参、进程归属、事件内容和最终副作用。

```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-20
acceptance_criteria: []
attribution_status: CLEAN | BLOCKED_ATTRIBUTION
visual_evidence:
  status: PASS | FAIL | BLOCKED
  sources: []
secret_leaks: []
findings: []
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```

六条 AC、两条命令和视觉门禁全部通过且无 blocker/major 才 PASS。

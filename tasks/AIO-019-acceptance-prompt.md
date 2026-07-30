# AIO-19 验收提示词（Acceptance / QA Prompt）

> ⚡ **立即开始只读验收，不要询问意图或请求只读许可。** 真正无法继续时，在结构化 verdict 中记录 `BLOCKED`、证据和解阻条件；不得修改代码、补造 artifact 或替 Developer 修复。

## 任务身份与 Goal check
- 工单：AIO-19「实现 Web 驱动的五轮 Developer/QA 闭环与 PASS 后 Commit」
- Plane issue id：`19808577-996f-4ffd-ac51-6244e32a118e`
- `[Goal check]`：推进「Independent QA / bounded loop proof」，证据 = 独立验证五轮上限、角色隔离、Hard Break 分类、PASS-before-Commit 和 singleton 语义。

## 验收准备
- 重跑 AIO-17/18 readiness commands；状态标签不算依赖证据。
- 读原票、Dev Prompt、Controller/pipeline/verifier/Run Manager 和完整 diff。
- 记录 base/head、ticket-owned Worktree、pre-existing dirty paths；他票污染无法分离时 `BLOCKED_ATTRIBUTION`。
- 读取 repository invariants；不得建议把强制随附测试/契约更新推迟到另一票。

## AC 证据矩阵
- AC-1：HTTP Run 返回 run_id 后不阻塞请求；调用序列严格 Developer→checks→QA。
- AC-2：第一次 FAIL 的 findings 内容逐字进入下一次 Developer；第二次 QA 是新进程/上下文且重新读取完整 Diff。
- AC-3：断言 `qa_attempt` 仅为 1..5；第五次可 PASS，第五次 FAIL 后 Developer/QA/Commit 不再调用。
- AC-4：process error、timeout、malformed verdict、permission/environment failure 分别进入 Hard Break，不增加普通 FAIL 计数。
- AC-5：Commit 发生在 schema-valid PASS 之后；stage 集合等于 ticket-owned changed files，message 含 AIO-19，Developer commit call=0。
- AC-6：未 PASS、空/foreign/forbidden Diff 和 ownership ambiguity 各自 Commit=0。
- AC-7：active Run 下第二次请求在任何新 Worktree/Agent 前拒绝。

## 必跑命令
```bash
python3 -m pytest tests/integration/test_web_agent_loop.py -q
python3 -m pytest tests/test_development_verifier.py tests/integration/test_ticket_pipeline.py -q
python3 -m pytest -q
```

不能只验证函数被调用；必须核对实参语义、顺序、call count、changed-file 集合和最终状态。所有外部 I/O 必须 fake/mock。

## Scope 与权限
- 禁止 Push/PR/Merge/deploy/Plane write、并行队列、任意 Resume、QA 写文件、Developer 自判 PASS。
- QA finding 只描述观察事实与最小实现修复，不得发明违反 main-green/commit-after-pass 的流程 remedy。

## Verdict
```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-19
acceptance_criteria:
  - id: AC-1
    status: PASS | FAIL | BLOCKED
    evidence: <command/test/file:line>
qa_attempts_observed: []
call_sequence: []
attribution_status: CLEAN | BLOCKED_ATTRIBUTION
findings: []
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```

全部 AC PASS、三条命令为 0、无 blocker/major、无归因或权限违规时才 PASS。


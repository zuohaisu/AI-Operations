# AIO-19 开发提示词（Developer Prompt）

> ⚡ **立即执行，不要询问用户重述目标。** 先完成只读 preflight，再在票内授权范围实施。真正 blocker 写入 Run artifact 并返回明确 Hard Break；不得把运行级失败伪装成普通 QA FAIL。

## 任务身份
- 工单：AIO-19「实现 Web 驱动的五轮 Developer/QA 闭环与 PASS 后 Commit」
- Plane issue id：`19808577-996f-4ffd-ac51-6244e32a118e`
- 优先级：high｜风险：R1｜Repository：`zuohaisu/AI-Operations`
- 依赖：AIO-17、AIO-18

## [Goal check]
本工作推进「Development → Independent QA → Bounded Fix Loop」阶段，证据 = Web Run API 在单一 owned Worktree 中执行最多五次完整 QA，PASS 后才由 Controller 创建 ticket-scoped Commit，Hard Break 与 QA FAIL 保持互斥。

## 启动前硬门禁
- AIO-17 readiness：`python3 -m pytest tests/test_web_service.py tests/test_local_config.py -q` 必须为 0。
- AIO-18 readiness：`python3 -m pytest tests/test_web_tickets.py tests/test_prompt_resolver.py -q` 必须为 0。
- 记录 checked-at、base SHA、ticket-owned Worktree、pre-existing dirty paths 和 active Run；Plane 状态不替代 readiness evidence。
- 盘点现有 `TicketController`、pipeline、development verifier、Run Manager 的调用方与守卫；列出改变 Commit/QA 顺序后会转红的全部测试。
- 若依赖、归因或现有状态机语义无法确定，Agent spawn=0，返回 `BLOCKED_REQUIREMENTS`。

## Repository invariants
- main 始终保持可交付；QA 前不得 Commit，PASS 后 Commit 只 stage 本 Run changed files。
- QA 是新的只读进程/上下文，不继承 Developer 自我判断，不修改文件。
- mandatory companion test/contract updates 留在本票，QA 不得建议推到未来票以接受红灯窗口。
- direct main push、auto merge、生产访问、Plane Done、并行 Run 均为 0。

## In scope
- Web `Run` 请求立即返回 `run_id`，后台创建一个 owned Run/Worktree 并顺序执行 Developer→deterministic checks→QA。
- Developer/QA 使用相互隔离的角色、上下文、进程和权限；QA 输入包含原票、Prompt、base→current Diff、changed files、check exit code 和 `qa_attempt`。
- QA 总轮次严格为 `1..5`。前四次 FAIL 可把**原始 findings**交回 Developer 做窄修复并完整重跑 checks+QA；第五次 FAIL 直接 `QA_EXHAUSTED`，不得再调用 Developer。
- QA PASS 仅表示可进入 Commit gate；Controller 验证非空、安全、ticket-owned Diff 后创建包含 issue key 的 Commit。Developer Agent 不运行 `git commit`。
- Developer/QA 进程失败、超时、畸形输出、权限/环境错误属于 Hard Break，立即停止并保留 artifacts；不消耗普通 QA FAIL 轮次。
- 同一 repository/Ticket 同时只允许一个 active Run。

## Out of scope
- 不 Push、不建 PR、不 Merge、不部署、不写 Plane Done/In Review。
- 不实现并行队列、自动选下一票、任意 Resume、远程访问或多用户权限。
- 不允许 QA 修改代码，不允许 Developer 自判 PASS 或扩大 findings。
- 不改 `.github/workflows/**`，不保存真实 Secret；改动文件不超过 20。

## 验收标准
- AC-1：点击 Run 立即得到 run_id，后台按 Developer→checks→QA 执行。
- AC-2：QA 首次 FAIL 后，Developer 只收到原始 findings；修复后使用全新只读 QA 上下文做完整第二轮验收。
- AC-3：第五次 QA 仍可 PASS；第五次 FAIL 后为 `QA_EXHAUSTED`，Developer/Commit 后续调用均为 0。
- AC-4：运行级 Hard Break 立即停止、保留 artifacts，且不计为普通 QA FAIL。
- AC-5：schema-valid PASS 后，Controller 只提交本 Run 文件，记录 branch/SHA；Developer 未 Commit。
- AC-6：未 PASS、空 Diff、forbidden path、越出 Worktree或无法归因时，Commit=0 并返回明确 Blocked/Hard Break。
- AC-7：已有 active Run 时第二次 Run 被拒绝，不产生第二组 Agent/Worktree。

## 确定性验证
```bash
python3 -m pytest tests/integration/test_web_agent_loop.py -q
python3 -m pytest tests/test_development_verifier.py tests/integration/test_ticket_pipeline.py -q
python3 -m pytest -q
```

必须覆盖 happy、one-fix、fifth-pass、fifth-fail、Hard Break、unsafe/foreign diff、duplicate Run。测试全部使用 fake Agent/临时仓库，不访问真实 Plane/GitHub/Agent。

## 实施与交付
1. 先画出现有调用序列和影响闭包，再做最小 adapter；不建第二套 Controller。
2. 用互斥结构化状态区分 PASS、FAIL、BLOCKED、HARD_BREAK、QA_EXHAUSTED。
3. 每轮记录输入 hash、findings、changed files、check evidence 和角色进程身份。
4. 输出 ticket-owned changed files、pre-existing dirty paths、三条测试命令/exit code、QA/Commit 调用序列和回滚方式。
- 回滚：`git revert` Web workflow adapter/策略，保留 artifacts；不得改写历史 verdict。
- Escalation：无法确定 finding 是否可修、Diff 归属或 Commit stage 白名单时 `BLOCKED_NEEDS_HUMAN`。


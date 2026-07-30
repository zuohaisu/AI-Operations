# AIO-20 开发提示词（Developer Prompt）

> ⚡ **立即执行，不要询问用户重述目标。** 先完成只读 preflight；真正 blocker 写入 append-only Run artifact 并返回 Hard Break。不得为了让页面“看起来有进度”伪造或覆盖事件。

## 任务身份
- 工单：AIO-20「实现 Run Timeline、Hard Break 人工介入与完整页面追踪」
- Plane issue id：`fca986c3-6482-43e6-8a45-6767cb4c3bf6`
- 优先级：high｜风险：R1｜Repository：`zuohaisu/AI-Operations`
- 依赖：AIO-19

## [Goal check]
本工作推进「Evidence retention / Human escalation」阶段，证据 = 页面从真实 append-only artifacts 恢复 Run 时间线，准确展示角色、轮次、findings、changed files、Hard Break、Retry/Stop 和 Commit，而不制造假进度或泄露 Secret。

## 启动前硬门禁
- 运行 `python3 -m pytest tests/integration/test_web_agent_loop.py -q`，确认 AIO-19 readiness。
- 盘点 Run state/events 的所有生产者与消费者、现有生命周期守卫和 Secret 流向；列出改变事件 schema 后必须同步的调用方/测试。
- 冻结 ticket-owned Diff、pre-existing dirty paths 和 owned process identity；依赖或归因不清时 Agent spawn=0。

## Repository invariants
- `events.jsonl` append-only；页面状态必须可追溯到 artifact，不得由前端猜测。
- Retry 不删除历史、不跳过 deterministic/QA/Commit 门禁；Stop 只触碰 owned process group。
- Hard Break 与 QA FAIL/PASS 分离；Secret 在 API、HTML、DOM、日志和磁盘原始事件中都不可见。
- mandatory companion schema/reader/test 更新留在本票，main 不得在两票之间保持红灯。

## In scope
- 每个 Run 写 append-only `events.jsonl` 与可恢复 `state.json`，事件含 timestamp、stage、role、round、status、artifact refs。
- 页面轮询 Run API，按真实事件显示 Planner/Developer/QA/Commit 顺序、Prompt 来源、findings、changed files、checks、branch/SHA。
- 浏览器关闭/重开后可恢复当前或最终状态，后台 Run 不因页面关闭停止。
- Hard Break 显示角色、阶段、轮次、原因、Worktree 和允许的人类动作。
- `Retry current stage` 沿用同一 run_id、保留历史，并重新经过该阶段之后的必要门禁。
- Stop 只终止本 Run owned process group，状态 `STOPPED`，保留 artifacts；提供安全的 Finder 入口。
- 对已知 Secret 做递归脱敏，且写磁盘前完成。

## Out of scope
- 不实现 WebSocket/SSE、数据库、任意节点 Resume、在线代码编辑器、通用 workflow designer。
- 不实现远程访问、多用户权限、Tailscale/Cloudflare、移动端或通知系统。
- 不自动修复 Hard Break，不允许跳过失败阶段继续。
- 不改 `.github/workflows/**`，不保存真实 Secret；改动文件不超过 16。

## 验收标准
- AC-1：经过 Planner、Developer、两次 QA 和 Commit 的 Run，Timeline 顺序/round/Prompt source/findings/changed files/SHA 与 artifacts 一致。
- AC-2：关闭再打开浏览器，同一 run_id 状态完整恢复，后台 Run 未停止。
- AC-3：Hard Break 页面显示角色、阶段、轮次、原因和 Worktree，且不显示为普通 FAIL/PASS。
- AC-4：Retry current stage 沿用 run_id、保留历史并重新经过后续门禁。
- AC-5：Stop 只终止 owned process group，状态 STOPPED，artifacts 保留。
- AC-6：配置 Secret 在 API/页面/DOM/日志/磁盘事件中均不可见。

## 确定性验证
```bash
python3 -m pytest tests/test_web_run_tracking.py tests/integration/test_web_hard_break.py -q
python3 -m pytest -q
```

另需浏览器/视觉证据：在至少 running、QA FAIL、Hard Break、COMPLETED 四种状态检查 Timeline 可读性、轮次/角色标签、错误操作入口、长 finding 溢出和 Secret 掩码。无法取得视觉证据时记录 human visual gate，UI 不得 PASS。

## 实施与交付
1. 先定义版本化事件 schema 和生产者/消费者影响闭包；避免页面直接读取进程内对象。
2. Retry/Stop 在副作用前校验 run ownership、stage eligibility 和 process identity。
3. 测试使用临时 Run/进程与 fake Secret；不得停止真实服务或访问真实外部系统。
4. 输出 changed files、dirty baseline、事件样例、测试 exit code、视觉证据状态和回滚方式。
- 回滚：`git revert` Timeline/control API/UI；保留 append-only artifacts。
- Escalation：进程归属、重试起点、事件真实性或 Secret 安全无法确认时 `BLOCKED_NEEDS_HUMAN`。


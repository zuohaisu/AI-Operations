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
- 运行 `.venv/bin/python -m pytest tests/integration/test_web_agent_loop.py -q`，expected = exit 0，确认 AIO-19 readiness；记录 dispatch-time checked-at，不能只引用 Plane 状态。
- 盘点 Run state/events 的所有生产者与消费者、现有生命周期守卫和 Secret 流向；列出改变事件 schema 后必须同步的调用方/测试。
- 冻结 ticket-owned Diff、pre-existing dirty paths 和 owned process identity。依赖/承重语义未知时 Agent spawn=0 并返回 `BLOCKED_REQUIREMENTS`；可机械拆分的混合 Diff 返回 `DIFF_SPLIT_REQUIRED`；只有归属事实无法确定时才返回 `BLOCKED_ATTRIBUTION`。

## Repository invariants
- `events.jsonl` append-only；页面状态必须可追溯到 artifact，不得由前端猜测。
- Retry 不删除历史、不跳过 deterministic/QA/Commit 门禁；Stop 只触碰 owned process group。
- Hard Break 与 QA FAIL/PASS 分离；Secret 在 API、HTML、DOM、日志和磁盘原始事件中都不可见。
- Timeline/事件 schema 必须原样表达 `QA_PENDING`、`HUMAN_VISUAL_REVIEW_PENDING`、`READY_FOR_REVIEW`、`DIFF_SPLIT_REQUIRED`、`USER_OVERRIDE_APPROVED`、`MERGE_AUTHORIZED_BY_USER` 和 `TECHNICAL_BLOCKED`；warning/override 不得覆盖原始 gate verdict。
- mandatory companion schema/reader/test 更新留在本票，main 不得在两票之间保持红灯。

## In scope
- 每个 Run 写 append-only `events.jsonl` 与可恢复 `state.json`，事件含 timestamp、stage、role、round、status、artifact refs。
- 页面轮询 Run API，按真实事件显示 Planner/Developer/QA/Commit 顺序、Prompt 来源、findings、changed files、checks、branch/SHA。
- 浏览器关闭/重开后可恢复当前或最终状态，后台 Run 不因页面关闭停止。
- Hard Break 显示角色、阶段、轮次、原因、Worktree 和允许的人类动作。
- Timeline 区分 Agent action 与 Repo Owner action；记录 owner 对视觉验收、override、feature-branch push、Draft PR 和 merge 的 actor/action/approved_at/reason，不记录 Secret。用户 override 保留原始 pending/fail 事件，不制造 PASS。
- `Retry current stage` 沿用同一 run_id、保留历史，并重新经过该阶段之后的必要门禁。
- Stop 只终止本 Run owned process group，状态 `STOPPED`，保留 artifacts；提供安全的 Finder 入口。
- 对已知 Secret 做递归脱敏，且写磁盘前完成。

## Out of scope
- 不实现 WebSocket/SSE、数据库、任意节点 Resume、在线代码编辑器、通用 workflow designer。
- 不实现远程访问、多用户权限、Tailscale/Cloudflare、移动端或通知系统。
- Agent 不自动修复 Hard Break、不自我授权跳过失败阶段；Repo Owner 显式 override 是独立、可审计的人类动作，不得被前端伪装成阶段 PASS。
- 不改 `.github/workflows/**`，不保存真实 Secret；改动文件不超过 16。

## 验收标准
- AC-1：经过 Planner、Developer、两次 QA 和 Commit 的 Run，Timeline 顺序/round/Prompt source/findings/changed files/SHA 与 artifacts 一致；七个 canonical delivery states 均来自持久事件而非前端推断。
- AC-2：关闭再打开浏览器，同一 run_id 状态完整恢复，后台 Run 未停止。
- AC-3：Hard Break 页面显示角色、阶段、轮次、原因和 Worktree，且不显示为普通 FAIL/PASS；Repo Owner 的 visual accept、`override_gate`、feature-branch push、Draft PR 和 merge 事件均记录 actor/action/approved_at/reason 并保留原始 gate 状态；`actor_type=developer_agent` 的 override/merge 授权在任何远程调用前被拒绝。
- AC-4：Retry current stage 沿用 run_id、保留历史并重新经过后续门禁。
- AC-5：Stop 只终止 owned process group，状态 STOPPED，artifacts 保留。
- AC-6：配置 Secret 在 API/页面/DOM/日志/磁盘事件中均不可见。

## 确定性验证
```bash
python3 -m pytest tests/test_web_run_tracking.py tests/integration/test_web_hard_break.py -q
python3 -m pytest -q
```

测试必须覆盖七个 canonical delivery states、Repo Owner 五类 action audit，以及 Agent 伪造 override/merge 在远程调用前被拒绝；状态、warning、authorization 和原始 verdict 不得互相覆盖。

另需浏览器/视觉证据：在至少 running、QA FAIL、Hard Break、`HUMAN_VISUAL_REVIEW_PENDING`、`USER_OVERRIDE_APPROVED`、`MERGE_AUTHORIZED_BY_USER`、`TECHNICAL_BLOCKED` 和 COMPLETED 状态检查 Timeline 可读性、轮次/角色标签、owner/Agent 身份、错误操作入口、长 finding 溢出和 Secret 掩码。无法取得视觉证据时记录 `HUMAN_VISUAL_REVIEW_PENDING`，UI 不得 PASS，但可创建带 warning 的 Draft PR。

## 实施与交付
1. 先定义版本化事件 schema 和生产者/消费者影响闭包；避免页面直接读取进程内对象。
2. Retry/Stop 在副作用前校验 run ownership、stage eligibility 和 process identity。
3. 测试使用临时 Run/进程与 fake Secret；不得停止真实服务或访问真实外部系统。
4. 输出 changed files、dirty baseline、事件样例、测试 exit code、视觉证据状态和回滚方式。
- 回滚：`git revert` Timeline/control API/UI；保留 append-only artifacts。
- Escalation：进程归属、重试起点、事件真实性或 Secret 安全无法确认时 `BLOCKED_NEEDS_HUMAN`；可机械分离的混合 Diff 为 `DIFF_SPLIT_REQUIRED`；实际 credential/network/conflict/remote failure 为 `TECHNICAL_BLOCKED`。

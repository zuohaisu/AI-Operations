# AIO-26 开发提示词（Developer Prompt）

> ⚡ **立即执行，不要询问用户重述目标。** 先完成只读 preflight；真正 blocker 写入 append-only Run artifact 并返回 Hard Break。不得删除任何 `prompt-metadata.json`，不得把孤儿记录标记为 READY。

## 任务身份
- 工单：AIO-26「Recover orphaned PREPARING prompt records so Prepare never deadlocks」（修复崩溃/被杀后 `PREPARING` 记录永久卡死导致 Prepare 死锁）
- Plane issue id：`d74403da-40e2-425c-8962-d1266b961be3`
- 优先级：medium｜风险：R1｜Repository：`zuohaisu/AI-Operations`
- 依赖：无。2026-07-31 的缺陷记录（run `aio-021-prompt-20260731080659928309-6b30c8`，已人工 finalize）记录了失败模式。

## [Goal check]
本工作推进「Deterministic Verification / Run 隔离健壮性」阶段，证据 = `PromptResolver.has_active_run()` 在活跃 owner 存在时仍单飞（single-flight），但能自恢复 owner 已死的孤儿 `PREPARING` 记录，使 Prepare 不再需要人工改 JSON 才能继续。

## 启动前硬门禁
- 运行 `.venv/bin/python -m pytest tests/ -q`，expected = exit 0，记录 dispatch-time checked-at（不能只引用 Plane 状态）。
- 只读盘点 `PromptResolver.has_active_run()`、`prepare()` 的全部生产者/消费者，以及 `prompt-metadata.json` / `state.json` 的写入方；确认改动 `has_active_run()` 的判定语义不会波及 `state.json` 的 ACTIVE 状态分支。
- 冻结 ticket-owned Diff、pre-existing dirty paths 与 owned process identity；归属事实无法确定时 Agent spawn=0 并返回 `BLOCKED_ATTRIBUTION`；可机械拆分的混合 Diff 返回 `DIFF_SPLIT_REQUIRED`。

## Repository invariants
- `prompt-metadata.json` 是 owned Run artifact：孤儿恢复必须**就地** finalize（读出→改字段→写回，保留全部既有字段），**绝不删除文件、绝不设为 READY**。
- 单飞语义不变：只要存在 owner 仍存活的 `PREPARING` 记录，`has_active_run()` 必须返回 True。
- 恢复终态复用现有 `HARD_BREAK_PLANNER` 契约（`planner_outcome: failed` + 非空 `hard_break_reason`），不新增状态枚举、不改 `_ACTIVE_STATES` 对 `state.json` 的原有处理。
- 不改 `WebAgentLoop`/`state.json` 的 ACTIVE 处理、不改 `ticket_controller` 生命周期记录或退出码、不加 UI、不加 HTTP 端点、不引入第三方依赖。

## In scope
- `PromptResolver.prepare()` 在写新 `prompt-metadata.json` 时记录 `owner_pid`（`os.getpid()`）与 ISO-8601 `created_at`（带时区，UTC）。
- `PromptResolver.has_active_run()` 判定 `PREPARING` 记录为孤儿的条件：
  - 记录含 `owner_pid` 且该 PID 已不存活；或
  - legacy 记录（无 `owner_pid`）且文件 mtime 早于 30 分钟的 stale 上限。
- 命中孤儿即就地 finalize 为 `status: HARD_BREAK_PLANNER`、`planner_outcome: failed`、`hard_break_reason` 明确指出是 orphan recovery；保留 `issue_key` 与其它既有字段；随后不计入活跃、继续扫描其余记录。
- 存活 owner 的 `PREPARING` 记录保持不变并使 `has_active_run()` 返回 True（单飞保留）。
- 在 `tests/` 增补单测覆盖：alive-owner blocking、dead-owner recovery、legacy-record timeout。
- 在 `src/ticket_autopilot/engine/README.md` 或模块 docstring 增补一段孤儿恢复规则说明。

## Out of scope
- 不改 `WebAgentLoop` 或 `state.json` 的 ACTIVE-state 处理。
- 不改 `ticket_controller` 生命周期记录或退出码。
- 无任何 UI 改动、不新增 HTTP 端点。
- 不引入第三方依赖。

## 实现要点（确定性，避免踩坑）
- PID 存活判定用 `os.kill(pid, 0)`：`ProcessLookupError` → 已死；`PermissionError` → 进程存在（视为存活）；`owner_pid` 非正整数或缺失按 legacy 分支处理，不得因异常把存活进程误判为死。
- PID 复用风险：把「liveness 检查」与「30 分钟 stale 上限」组合，legacy/无 PID 记录以 mtime 为上界兜底；含 owner_pid 的记录以 liveness 为准，避免把刚复用同一 PID 的无关进程误当 owner 而永久阻塞。
- 恢复写回复用现有 `_write_json`（`indent=2, sort_keys=True`），先 `json.loads` 既有内容再改字段，禁止整体覆盖丢字段。
- 30 分钟阈值以常量表达（如 `_STALE_PREPARING_SECONDS = 1800`），测试可通过构造文件 mtime / 注入时钟验证边界。

## 验收标准
- AC-1：给定 `owner_pid` 已不存活的 `PREPARING` 记录，调用 `has_active_run()` 返回 False，且该记录文件被改为 `HARD_BREAK_PLANNER`、`planner_outcome: failed`、非空 `hard_break_reason`。
- AC-2：给定 `owner_pid` 仍存活的 `PREPARING` 记录，`has_active_run()` 返回 True 且记录不变（单飞保留）。
- AC-3：给定无 `owner_pid` 的 legacy `PREPARING` 记录且文件 mtime 早于 30 分钟，`has_active_run()` 按 AC-1 恢复；更年轻的 legacy 记录仍阻塞。
- AC-4：新的 `prepare()` 写出的 `prompt-metadata.json` 含调用方 `owner_pid` 与 ISO-8601 `created_at`。
- AC-5：任何孤儿恢复后，原 `issue_key` 及既有字段保留，且没有任何 `prompt-metadata.json` 被删除。

## 确定性验证
```bash
python3 -m pytest tests/ -q
```
- Pass：全套绿灯（含新增孤儿恢复测试），exit 0。
- Fail：任何红灯进入有界修复环（最多 5 轮 QA），耗尽后 HARD_BREAK。

测试须用临时 artifacts 目录与可控 PID/mtime（如已退出的子进程 PID、人为回拨 mtime），不得依赖真实运行中的服务或系统当前时间产生 flaky 结果。

## 实施与交付
1. 先改 `prepare()` 写 `owner_pid` + `created_at`（AC-4），再改 `has_active_run()` 的 `PREPARING` 分支加入孤儿判定与就地恢复。
2. 增补 `tests/` 单测覆盖三种场景（存活阻塞 / 死亡恢复 / legacy 超时），显式断言文件终态字段与「未删除」。
3. 在 engine README 或模块 docstring 记录孤儿恢复规则。
4. 输出 changed files、dirty baseline、新增测试样例、`pytest` exit code 与回滚方式；**不 commit**。

## 回滚与升级
- 回滚：单次 `git revert` 本 PR；已恢复的 metadata 文件保留其证据，无需迁移。
- Escalation：若发现单飞语义或 `state.json` ACTIVE 处理必须联动才能正确恢复 → `BLOCKED_NEEDS_HUMAN` 说明具体诉求，不要顺手改 out-of-scope 文件；实际 credential/network/conflict/remote failure 为 `TECHNICAL_BLOCKED`。

## 人工点位
- Trigger：Repository owner 将 issue 置为 In Progress。
- Gate：Repository owner 审阅并合并 PR。
- Owner authority：owner 可在 QA pending 时创建 Draft PR 并显式授权 merge；所有 override 保留原始证据并记录 actor/action/approved_at/reason。
- Override policy：`QA_PENDING` / `HUMAN_VISUAL_REVIEW_PENDING` 可伴随 Draft PR；失败的验证绝不报告为 PASS。

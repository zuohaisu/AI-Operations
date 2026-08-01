# AIO-26 验收提示词（Acceptance / QA Prompt）

> ⚡ **立即开始只读验收，不要询问意图或请求只读许可。** 真正 blocker 写入 verdict；不得修改任何 `prompt-metadata.json`、不得删除记录、不得停止未知进程或用人工补数据美化结果。

## 任务身份与 Goal check
- 工单：AIO-26「Recover orphaned PREPARING prompt records so Prepare never deadlocks」
- Plane issue id：`d74403da-40e2-425c-8962-d1266b961be3`
- 优先级：medium｜风险：R1｜Repository：`zuohaisu/AI-Operations`
- `[Goal check]`：推进「Independent QA / Run 隔离健壮性」，证据 = 交叉核对 `has_active_run()` 对存活 owner 的单飞保留、对死亡 owner / 超时 legacy 记录的就地恢复，以及「绝不删除、绝不 READY、保留原字段」的不变量。

## 验收准备
- 重跑 `.venv/bin/python -m pytest tests/ -q`，expected = exit 0，记录本次 checked-at；票状态不是能力证据。
- 读原票、Dev Prompt、`prompt_resolver.py` 的 `has_active_run()`/`prepare()` diff，以及新增测试。
- 记录 base/head、ticket-owned files 与 pre-existing dirty paths；可机械拆分的混合 Diff 为 `DIFF_SPLIT_REQUIRED`，仅归属事实无法确定时才 `BLOCKED_ATTRIBUTION`。
- 所有验收在临时 artifacts 目录/临时进程内进行，不得触碰用户真实运行中的服务或 Run。

## AC 证据矩阵
- AC-1：构造 `owner_pid` 已不存活的 `PREPARING` 记录 → `has_active_run()` 返回 False，且该文件读为 `HARD_BREAK_PLANNER` + `planner_outcome: failed` + 非空 `hard_break_reason`（内容指向 orphan recovery）。
- AC-2：构造 `owner_pid` 存活（如当前进程 PID 或存活子进程）的 `PREPARING` 记录 → 返回 True 且文件逐字节不变（比对前后内容）。
- AC-3：构造无 `owner_pid`、mtime 早于 30 分钟的 legacy 记录 → 按 AC-1 恢复；另构造 mtime 在 30 分钟内的 legacy 记录 → 仍返回 True 且不被改写（边界两侧都要有证据）。
- AC-4：新 `prepare()` 写出的 `prompt-metadata.json` 含调用方 `owner_pid`（等于该进程 PID）与可被 `datetime.fromisoformat` 解析的带时区 `created_at`。
- AC-5：任一恢复后核对原 `issue_key` 及既有字段仍在，且目录中 `prompt-metadata.json` 数量不减少（无文件被删除）。

## 必跑命令
```bash
python3 -m pytest tests/ -q
```
- 全套绿灯（含新增孤儿恢复测试）、exit 0 才算确定性门禁通过。

## 本项目专属检查（必查）
- **就地恢复不丢字段**：审阅恢复写回逻辑，确认是「读出→改字段→写回」而非整体覆盖；`git diff` 中 `has_active_run()` 不得出现 `unlink`/`os.remove`/`rmtree` 等删除调用。
- **PID 判定正确**：`PermissionError`（进程存在但非本用户）必须视为「存活」，不能误判为死亡而错误恢复一个仍在跑的 prepare。
- **单飞未被削弱**：存活 owner 场景 `has_active_run()` 必须仍返回 True；不得为了「能恢复」而放宽到任何 `PREPARING` 都算孤儿。
- **范围边界**：`git status --porcelain` 中改动应限于 `src/ticket_autopilot/services/prompt_resolver.py`、`tests/` 下的新增/修改测试、`engine/README.md` 或模块 docstring 的说明；不应出现 `web.py`、`state.json` 处理、`ticket_controller`、UI/静态资源或任何第三方依赖引入。
- **时间可注入/可控**：测试构造过期/未过期边界应通过设定文件 mtime 或注入时钟，而非 sleep/依赖系统当前时间（避免 flaky）。

## QA 权限与 Verdict
- 只读：可读所有文件、跑只读命令；不得改文件、不补做缺失内容、不放松 AC。
- 不以「函数被调用」证明正确；核对实际文件终态、返回值、字段保留与「未删除」这几项副作用。

```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-26
acceptance_criteria: []
attribution_status: CLEAN | DIFF_SPLIT_REQUIRED | BLOCKED_ATTRIBUTION
visual_evidence:
  status: NOT_APPLICABLE   # 本票无 UI 改动
  reason: "no UI or HTTP surface changed"
secret_leaks: []
findings: []
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```

## 禁止事项
- 不修改任何被验收的文件、不删除任何 `prompt-metadata.json`、不放松 AC。
- **AC-1/AC-3 若孤儿记录被删除或被标为 READY → 直接 FAIL（blocker）**：这违反 owned-artifact 保留与状态契约。
- **AC-2 若存活 owner 的 `PREPARING` 被误恢复 → 直接 FAIL（blocker）**：破坏单飞语义，是本票最危险的回归。
- 五条 AC 与确定性命令全部通过且无 blocker/major 才 PASS。

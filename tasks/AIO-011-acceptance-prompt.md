# AIO-11 验收提示词（Acceptance / QA Prompt）

> 独立 QA agent 只读验收。禁止编辑、清理真实 Worktree/分支、Commit、Push、建 PR 或改 Plane。

## 任务身份与 Goal check
- 工单：AIO-11「实现 Disposable Run、Worktree 与角色分级权限」
- Plane issue id：`f893213b-41ae-41d4-8522-305f9478faaa`
- `[Goal check]`：推进「Independent QA」，证据 = 在临时仓库证明 Run 隔离、角色权限和 cleanup 安全，并给出 PASS/FAIL/BLOCKED。

## 验收准备
- 读原票、开发提示词、AIO-9 Guardrails、AIO-10 ticket-spec 和待验收 diff。
- 记录 Git 状态/base/head/改动范围；只在测试创建的临时仓库验证。
- 不运行任何面向用户真实 Worktree/branch 的 cleanup。

## AC 证据矩阵
- AC-1：创建两个 Run，证明 run_id、state/artifacts、Worktree、branch 唯一且 base SHA 正确。
- AC-2：Developer 合法写入放行；越 Worktree、main/master、越权工具均在 spawn 前抛 `SecurityError`。
- AC-3：Planner/QA 的 Write/Edit/Bash 请求均被拒，确认不是依赖外部 CLI 自觉。
- AC-4：临时仓库中的未合并 disposable Run 可清理，日志/verdict 保留。
- AC-5：已合并、main/master、未知/不明确目标均拒绝；断言没有删除副作用。

## 必跑命令
```bash
python3 -m pytest tests/test_run_worktree.py tests/test_role_guardrails.py -q
python3 -m pytest -q
```
所有 exit code 必须为 0；若测试触碰真实仓库资源、缺少负向断言或通过放宽 AIO-9 默认策略实现，判 FAIL。

## 范围与安全
- 不应出现 PR、Plane 状态、QA 路由、产品 CLI、auto-merge、main push、生产/迁移、resume/并行/容器。
- 检查路径解析是否防逃逸、清理是否有所有权与分支保护；任何潜在误删为 blocker。

## Verdict
输出 `verdict`、AIO-11 的 AC-1～AC-5 状态与命令/file:line 证据、findings、`scope_violation`、`recommended_next_state`。全部 AC PASS 且无 blocker/major 才 PASS；发现缺陷只描述最小修复，不代为修改。

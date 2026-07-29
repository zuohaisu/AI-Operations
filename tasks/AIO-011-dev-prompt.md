# AIO-11 开发提示词（Developer Prompt）

> 交给开发 agent。开始前读 `AGENTS.md`、`IDEA.md`、AIO-9/AIO-10 交付物，并输出 `[Goal check]`。

## 任务身份
- 工单：AIO-11「实现 Disposable Run、Worktree 与角色分级权限」
- Plane issue id：`f893213b-41ae-41d4-8522-305f9478faaa`
- 优先级：high｜风险：R1｜依赖：AIO-9、AIO-10

## [Goal check]
本工作推进「Development isolation」阶段，证据 = 每个 Run 有独立 Worktree/branch/artifacts，Developer 仅在该 Worktree 可写，Planner/QA 保持只读。

## In scope
- Run Manager：`run_id`、`state.json`、artifact 目录、base SHA、branch、attempt、时间戳。
- 创建 `.ticket-autopilot/worktrees/{run_id}/` 与独立 feature branch；拒绝 main/master。
- 增加最薄 Git/Worktree service，复用本机 Git 和既有 Engine。
- 将 AIO-9 全局只读策略细化为角色/节点边界：Developer 只在指定 Worktree 内写/Commit；Planner/QA 只读。
- 安全 cleanup：只删除可确认的 disposable Worktree/允许删除的未合并本地分支，保留日志和 verdict。

## Out of scope
- 测试结果判定、PR/Plane 写回、QA 路由、产品 CLI。
- auto-merge、main push、生产、迁移、远程已合并分支删除。
- resume、并行 Run、容器、daemon；不得新建第二个 Engine。

## 验收标准
- AC-1：合法 ticket-spec 创建唯一 Run、state/artifacts、Worktree、feature branch、base SHA。
- AC-2：Developer 在指定 Worktree 内的允许写操作放行；越界路径、main 或越权工具在 spawn 前 `SecurityError`。
- AC-3：Planner/QA 请求 Write/Edit/Bash 等能力时仍被 AIO-9 护栏拒绝。
- AC-4：cleanup 清理未合并 disposable 资源，但保留日志/verdict。
- AC-5：已合并分支、main/master 或目标不明确时拒绝清理并返回 Blocked。

## 确定性验证
```bash
python3 -m pytest tests/test_run_worktree.py tests/test_role_guardrails.py -q
```
所有 Git 操作必须只发生在测试临时仓库。任何越权写、main 操作、日志丢失或误删即失败，不得通过放松 AIO-9 默认护栏修复。

## 完成定义与执行
1. 先审查 AIO-9 GuardrailPolicy 和 AIO-10 ticket-spec 接口，定义最小 Run/Worktree 契约。
2. 使用显式、可校验的绝对目标解析；清理前确认所有权、分支和合并状态。
3. 为每条 AC 写正反向测试，尤其验证 spawn 前拒绝和未知目标不删除。
4. 运行票内命令及相关回归；Commit message 含 `AIO-11`。
5. 输出 Developer Summary；不建 PR、不改 Plane、不推 main。

## 风险、回滚与人工点位
- 风险：策略过宽会越权，cleanup 错判会误删用户资源。
- 回滚：`git revert` 新服务/策略；绝不以破坏性 Git 命令清理用户工作区。
- Trigger：AIO-10 PASS 后进入 In Progress。
- Gate：人工 Review Developer 写边界、main 保护、cleanup 目标解析。
- Escalation：不能确定资源归属或合并状态时 `BLOCKED_NEEDS_HUMAN`。

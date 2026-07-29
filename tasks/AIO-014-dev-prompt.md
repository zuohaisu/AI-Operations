# AIO-14 开发提示词（Developer Prompt）

> 开发 agent 开始前读 `AGENTS.md`、`IDEA.md`、AIO-11/AIO-13 接口和当前 CLI 入口，并输出 `[Goal check]`。

## 任务身份
- 工单：AIO-14「接通 ticket-controller CLI 与干净环境安装」
- Plane issue id：`550a1f3c-4cac-458b-bed7-252045fd2f12`
- 优先级：high｜风险：R1｜依赖：AIO-13

## [Goal check]
本工作推进「Usable local entrypoint」阶段，证据 = `ticket-controller` 可在干净 Python 3.11+ 环境安装，并以可信退出码完成 run/status/cancel/cleanup。

## In scope
- `ticket-controller run ISSUE_KEY` 接 AIO-13 真实 workflow，删除 `[stub]` success。
- `status`/`cancel`/`cleanup` 读取 Run state，并遵守 AIO-11 disposable/safe cleanup 语义。
- READY/Blocked/Cancelled/active-run 映射为稳定、无歧义退出码。
- credentials/repository/Agent CLI/config preflight 在 Agent 或外部写入前失败。
- 补齐 `pyproject.toml` runtime/dev-test dependencies 与 Python 3.11+ 干净环境安装/帮助/冒烟测试。
- 文档给 Plane-first 的最短配置和四命令路径；Secret 仅来自环境。

## Out of scope
- Web UI、daemon/queue、parallel/resume、auto-merge/deploy、自动选票。
- Linear/GitHub Issues intake、双 Agent 备份。
- CLI 测试中的真实 Plane/GitHub/Agent 请求。

## 验收标准
- AC-1：干净 3.11+ 安装后 `--help` 列出 run/status/cancel/cleanup，不含 resume。
- AC-2：合法 key + preflight 通过时走真实 Controller，输出 run_id/最终状态，无 stub。
- AC-3：缺凭证/仓库/Agent CLI/active run 时在外部写前返回可操作错误与非零退出码。
- AC-4：status 输出状态、节点、Worktree、Branch、PR、attempt、更新时间、Blocked reason。
- AC-5：cancel 安全终止本 Run 子进程并标 CANCELLED；cleanup 仅清理确认的本地 disposable 资源，保留日志。
- AC-6：Blocked/Cancelled/stalled 退出码均非 0。

## 确定性验证
```bash
python3 -m pytest tests/test_cli.py tests/integration/test_cli_lifecycle.py -q
```
安装/help/lifecycle/exit code/preflight 全部隔离、无网络。stub、Blocked=0、cleanup 越界、依赖漏声明或 clean install 失败均为 FAIL。

## 执行指引
1. 先盘点 console entrypoint 和 stub，定义命令/退出码契约，复用已有 Controller/Run Manager。
2. preflight 必须早于 Agent spawn/外部写；错误不打印 Secret。
3. cancel/cleanup 使用已验证 run_id 和归属，不猜测 PID/路径/branch。
4. 用隔离临时环境/临时仓库写测试，跑票内命令及全套回归；Commit 含 `AIO-14`。
5. 更新最短使用文档；输出 Developer Summary，不改真实 Plane、不自行建 PR/merge/push main。

## 风险、回滚与人工点位
- 风险：错误 code 0 制造假成功；目标误判终止/删除他人资源。
- 回滚：保留 Engine CLI 诊断入口，`git revert` 产品 CLI，不清理未知资源。
- Gate：人工在干净环境复现 install/help/mock lifecycle。
- Escalation：cleanup 目标、凭证来源或 Agent CLI 身份不明时 `BLOCKED_NEEDS_HUMAN`。

# AIO-14 验收提示词（Acceptance / QA Prompt）

> 独立 QA 只读验收。不得修改环境声明/代码，不得取消或清理真实 Run，不触发外部服务。

## 任务身份与 Goal check
- 工单：AIO-14「接通 ticket-controller CLI 与干净环境安装」
- Plane issue id：`550a1f3c-4cac-458b-bed7-252045fd2f12`
- `[Goal check]`：推进「Independent QA」，证据 = clean install、四命令、preflight 与退出码契约可重复验证。

## 验收准备
- 读原票、开发提示词、CLI entrypoint、pyproject、Run Manager 和 diff。
- 记录 Git status/base/head；只使用测试临时环境/仓库。
- 不将系统当前已安装依赖视为“干净环境安装”证据。

## AC 逐条验收
- AC-1：隔离 Python 3.11+ 安装成功；help 有 run/status/cancel/cleanup，无 resume。
- AC-2：mock 合法 run 确认调用真实 Controller，输出 run_id/status，源码与输出均无 `[stub]`。
- AC-3：缺 credential/repository/Agent CLI/active run 分别非 0，且外部写/Agent 调用为 0。
- AC-4：status 对 active/blocked/finished fixtures 输出全部承重字段。
- AC-5：在临时资源验证 cancel/cleanup；本 Run 资源被处理、日志保留、未知资源不碰。
- AC-6：Blocked/Cancelled/stalled 均非 0；只有契约定义的成功可返回 0。

## 必跑命令
```bash
python3 -m pytest tests/test_cli.py tests/integration/test_cli_lifecycle.py -q
python3 -m pytest -q
```
记录 exit code 和关键测试。若测试访问真实 Plane/GitHub/Agent、依赖本机污染环境或可能清理用户资源，判 FAIL/BLOCKED。

## Scope 与安全
- 不应出现 UI/daemon/queue/parallel/resume/auto-merge/deploy/其他 intake。
- 检查日志及异常中无 token/secret；cleanup/cancel 目标必须由 run ownership 确认。

## Verdict
输出 AIO-14 `verdict`、AC-1～AC-6 的 evidence、findings、scope/security violation、recommended state。任一退出码语义错误、stub 残留或清理越界均为 blocker。

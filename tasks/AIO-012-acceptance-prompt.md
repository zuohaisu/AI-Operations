# AIO-12 验收提示词（Acceptance / QA Prompt）

> 独立 QA 只读验证，不修改代码/测试/证据，不建 PR、不改 Plane。

## 任务身份与 Goal check
- 工单：AIO-12「实现确定性开发验证与工程证据归档」
- Plane issue id：`dce4a1df-7d8f-4a5c-b6a0-f424a6fe1f6e`
- `[Goal check]`：推进「Independent QA」，证据 = 证明成功判定完全来自 Git/Scope/exit code，evidence bundle 完整且失败不会流向 PR。

## 验收前
- 读原票、开发提示词、ticket-spec、Run/artifact 接口和 diff。
- 记录 Git status/base/head/改动范围；测试只可使用临时仓库。
- 不把 Developer Summary、日志中的自然语言“成功”视为证据。

## AC 逐条验证
- AC-1：无新 Commit 时为 `BLOCKED_ENVIRONMENT`，断言 GitHub 未调用。
- AC-2：分别构造空 Diff、冲突、错误 commit message，检查明确结果与证据。
- AC-3：多条 verification/check 均在 Worktree 执行，逐条保存 command/cwd/stdout/stderr/exit/time。
- AC-4：任一 exit 非 0 时 verified=false，PR/后续成功动作未发生。
- AC-5：happy path evidence bundle 字段齐全、稳定、可被 QA Connector 直接解析。
- AC-6：forbidden_paths 与 max_changed_files 各有负向测试，结果为 `BLOCKED_NEEDS_HUMAN`。

## 必跑命令
```bash
python3 -m pytest tests/test_development_verifier.py -q
python3 -m pytest -q
```
记录 exit code 和关键测试名。若没有副作用隔离、cwd/timeout 约束或只验证 happy path，判 FAIL。

## 范围检查
- 不得实现 PR/真实 Plane/GitHub、QA schema、CLI、Dashboard。
- 不得执行网络、生产、迁移、交互或不可逆命令；不得泄露凭证。

## 输出要求
结构化输出 `verdict: PASS|FAIL|BLOCKED`、AIO-12 AC-1～AC-6 的状态与证据、findings（severity/type/evidence/required_fix）、`scope_violation` 和 `recommended_next_state`。任一 AC FAIL 或 blocker/major 即 FAIL；环境不能安全验证则 BLOCKED。

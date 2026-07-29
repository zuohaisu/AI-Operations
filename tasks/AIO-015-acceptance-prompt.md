# AIO-15 验收提示词（Acceptance / QA Prompt / Real Pilot）

> 独立 QA 只读验收真实 Pilot。不得修改文档/证据/Plane/PR，不得补跑 Developer，也不得把人工补步骤算作自动闭环。

## 任务身份与 Goal check
- 工单：AIO-15「用闭环文档更新运行首张真实 R0 Pilot」
- Plane issue id：`c99bc58f-73b2-4e4c-a9e4-68081f54368d`
- `[Goal check]`：推进「Independent QA + Pilot proof」，证据 = 从真实 Run 回读全链证据并确认人工 Prompt 复制为 0。

## 前置真实性检查
- 确认 AIO-10～14 在本次 Pilot 前已 QA PASS 且合并。
- 回读启动记录：唯一入口应为 `ticket-controller run AIO-15`。
- 记录 run_id、base/head、branch、commit、artifact paths、qa_attempt、PR URL、Plane state。
- 任一环节由人手工代替 Controller，Pilot 判 FAIL/BLOCKED，不能补证。

## AC 逐条验收
- AC-1：时间线和 artifacts 证明 Controller 自动完成所有阶段，人工 Prompt copy count=0。
- AC-2：目标文档出现三个 Connector 路径，且无陈旧 `not yet present` 断言。
- AC-3：base→head Diff 只含 `docs/closed-loop-workflow.md`；若 tracked Run artifacts 属预期，须单列解释；`src/`/tests 产品改动为 FAIL。
- AC-4：qa-verdict 可通过 schema，verdict=PASS，每条 AC 有证据。
- AC-5：独立 feature branch、非空 Commit/Diff、Draft PR 均存在；Plane 回读为 In Review，绝非 Done。
- AC-6：检查 Controller 最终状态与日志，无门禁失败后假报 success。

## 必跑与回读
```bash
python3 -c "from pathlib import Path; t=Path('docs/closed-loop-workflow.md').read_text(); assert 'connectors/plane.py' in t; assert 'connectors/github.py' in t; assert 'connectors/qa.py' in t; assert 'not yet present' not in t"
git diff --name-only <base_sha>..<head_sha>
git show --stat --oneline <head_sha>
```
同时通过 Connector/API 只读回读 PR draft 标记与 Plane state；状态码成功但字段值错误不能算 PASS。

## 安全指标
- manual prompt copy=0；direct main push=0；auto merge=0；production access=0。
- 不泄露凭证，不把 Done-before-review 当成功。

## Verdict
输出 `verdict: PASS|FAIL|BLOCKED`、AIO-15 AC-1～AC-6、每项来源（artifact/file/commit/PR/Plane）与指标。只有全链真实、范围干净、QA PASS、Draft PR、In Review 同时成立才 PASS。

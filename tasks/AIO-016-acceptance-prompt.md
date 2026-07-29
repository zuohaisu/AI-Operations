# AIO-16 验收提示词（Acceptance / QA Prompt / Graduation Gate）

> 独立 QA 只读审计三次真实 Pilot。不得补写 manifest、修产品、改历史 verdict、修改 Plane/PR 或用 mock 替代真实证据。

## 任务身份与 Goal check
- 工单：AIO-16「完成两张额外低风险 Pilot 与 v0.1 Graduation Gate」
- Plane issue id：`27f47a4f-14cc-425a-8882-cefbfb1bf989`
- `[Goal check]`：推进「Independent QA / graduation decision」，证据 = 对三条 Run 做来源可追溯的完整性、安全性与指标审计。

## 启动资格
- 回读 AIO-15 及两张 Plane dependency；确认三票均是真实 R0/R1，后两票在 AIO-16 In Progress 前已链接。
- 若候选缺失、不合格或使用 mock/manual verification，直接 BLOCKED/FAIL，不继续计算毕业指标。

## AC 证据矩阵
- AC-1：manifest 恰有三条真实 Run；逐条交叉核对 ticket-spec、commit/diff、checks exit、qa-verdict、PR/Blocked、Plane state。
- AC-2：独立回读得出 ≥2 In Review、prompt copy=0、pre-review human intervention 每票≤1。
- AC-3：证据不足或 QA 非 PASS 的 Run 没有成功状态；False PASS=0。
- AC-4：Git/PR/Run 证据证明 direct main push=0、auto merge=0、production access=0、evidence retention=100%。
- AC-5：每个产品 finding 链接独立窄票；原 artifacts/verdict 未被修改美化。
- AC-6：删除任一记录/承重字段或改坏指标的负向 fixture 会使 verifier 非 0。

## 必跑命令
```bash
python3 -m pytest tests/integration/test_pilot_evidence.py -q
```
并对每条 manifest 记录执行只读交叉回读。JSON 自称 PASS 不算证据；需验证真实 commit/PR draft/Plane state/qa schema/check exit。

## 毕业指标
```yaml
real_runs: 3
in_review_minimum: 2
false_pass: 0
manual_prompt_copy: 0
direct_main_push: 0
auto_merge: 0
production_access: 0
evidence_retention_percent: 100
```
任一指标不达标，`verdict: FAIL`，`graduation_recommendation: REMAIN_PILOT`。

## Scope / tamper 检查
- 确认 AIO-16 未夹带产品缺陷修复、R2/R3、生产/迁移、parallel/resume/UI。
- 比对 artifacts 时间戳/commit/PR/Plane 历史，发现补造、改写或人工代 QA 为 blocker。

## 输出格式
```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-16
pilot_records:
  - issue_key: <key>
    evidence_complete: true | false
    actual_state: <state>
metrics:
  false_pass: <n>
  evidence_retention_percent: <n>
acceptance_criteria:
  - id: AC-1
    status: PASS | FAIL
    evidence: <source>
findings: []
graduation_recommendation: GRADUATE_V0_1 | REMAIN_PILOT | BLOCKED_NEEDS_HUMAN
```
只有六条 AC 全 PASS、所有安全指标达标且无 blocker/major，才可建议 `GRADUATE_V0_1`；最终宣布权仍属于 PM。

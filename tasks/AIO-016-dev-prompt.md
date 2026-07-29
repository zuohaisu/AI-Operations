# AIO-16 开发提示词（Developer Prompt / Graduation Gate）

> 这是一张 Pilot 证据与毕业门禁票，不是在票内暗修产品缺陷。进入 In Progress 前，PM 必须在 Plane Dependencies 中链接两张合格的真实 R0/R1 候选票。

## 任务身份
- 工单：AIO-16「完成两张额外低风险 Pilot 与 v0.1 Graduation Gate」
- Plane issue id：`27f47a4f-14cc-425a-8882-cefbfb1bf989`
- 优先级：medium｜风险：R1｜依赖：AIO-15 + 两张待 PM 链接的 R0/R1 候选票

## [Goal check]
本工作推进「v0.1 graduation evidence」阶段，证据 = 三个真实 Run 的机器可读 manifest 证明 ≥2 In Review、False PASS=0、越权=0、证据保留率=100%。

## 启动前硬门禁
- AIO-15 已完成并保留全部证据。
- 两张候选票必须结构完整、R0/R1、无生产/迁移/manual verification，并在 Plane 建立明确依赖。
- 任一条件不满足，本票保持 Backlog 或 `BLOCKED_NEEDS_HUMAN`，不得启动。

## In scope
- 用 `ticket-controller` 分别运行两张候选票，不复制 Prompt、不绕过门禁。
- 至少覆盖 happy path；自然出现 QA FAIL 时保留 one-fix/exhausted 证据，不能人为制造生产风险。
- 新增 `logs/pilots/v0.1-pilot-manifest.json`，收录三票的 run_id、key、risk、commit、checks、QA、PR、Plane state、人工干预、安全事件。
- 新增只读 evidence test，检查三条记录、≥2 In Review、False PASS=0、main push=0、production access=0、证据完整率=100%。
- Pilot 暴露的每个产品缺陷另建窄票，原 Run 结果不修改/美化。

## Out of scope
- 不在本票修产品缺陷；不纳入 R2/R3、生产、迁移、auto-merge、parallel/resume/UI。
- mock run、手工 Prompt、人类代 QA 不计入三张 Pilot。

## 验收标准
- AC-1：manifest 有三个真实可回读 Run，逐项含 ticket-spec、Commit/Diff、exit code、QA、PR/Blocked、Plane state。
- AC-2：≥2/3 In Review；人工 Prompt copy 总数=0；最终 Review 前人工干预每票≤1。
- AC-3：证据不足或 QA 非 PASS 的 Run 只能 Blocked，False PASS=0。
- AC-4：direct main push=0、auto merge=0、production access=0、完整证据保留率=100%。
- AC-5：产品 finding 均有独立后续票，原 Run 不被改写。
- AC-6：少于 3 条或承重字段/指标未达标时 verifier 非 0，v0.1 不得宣称完成。

## 确定性验证
```bash
python3 -m pytest tests/integration/test_pilot_evidence.py -q
```
通过还需独立 QA PASS。任何假成功、证据缺失、安全事件、人工代替 Agent/QA 或指标不足即 FAIL；产品保持 Pilot/Beta。

## 执行指引
1. PM 先在 Plane 写清两张候选依赖并复核风险/verification。
2. 逐票只通过 `ticket-controller run ISSUE_KEY` 启动，失败如实保留。
3. 从真实 artifacts/PR/Plane 回读构建 manifest，不手工臆测字段。
4. evidence test 必须默认失败于缺字段/指标不足，并覆盖 tampering/false-pass 负向场景。
5. Commit message 含 `AIO-16`；独立 QA 后由 PM 根据证据决定是否宣布 v0.1。

## 风险、回滚与人工点位
- 风险：选票偏差或人工补步骤夸大成功率；失败留下分支/PR/state。
- 回滚：用 AIO-14 cleanup 只清确认的本地 disposable 资源，保留远程证据与历史 verdict；manifest 通过 PR/revert 回退。
- Gate：PM 审阅 manifest、独立 QA、安全指标。
- Escalation：候选不合格或指标不可由证据计算时 `BLOCKED_NEEDS_HUMAN`。

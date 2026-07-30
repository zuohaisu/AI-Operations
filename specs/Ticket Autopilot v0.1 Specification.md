# Ticket Autopilot v0.1 Specification

**Version:** 0.1
**Status:** Approved as a fallback design; implementation pending reuse-first capability audit
**Date:** 2026-07-20
**Primary objective:** 验证单个软件开发 Ticket 的 `Development → QA → Fix → QA` 自动闭环质量。

---

> **2026-07-22 alignment gate:** This specification describes a local Python
> Controller, but it is not authorization to rebuild capabilities already available
> through Linear or Plane automation, agent hooks, MCP, GitHub Actions, or native
> GitHub integrations. Before implementation, inventory those capabilities and record
> the remaining gaps. Use this Controller only for the smallest set of gaps that cannot
> be closed by configuration or thin deterministic glue. See `IDEA.md`.

---

## 1. Product Definition

Ticket Autopilot v0.1 是一个运行在本地的 Python Controller。

它以一张结构化的 Linear Issue 为输入，在隔离的 Git Worktree 中调用 Developer Agent 完成开发，再调用独立 QA Agent 验收。QA 失败时，Controller 最多自动执行两轮修复。

最终输出是一张：

* 已完成代码修改
* 已通过确定性测试
* 已通过独立 AI QA
* 等待人工 Review 和 Merge

的 GitHub Pull Request。

### 1.1 v0.1 的核心价值

当前流程中，人需要手工完成：

* 从 Linear 读取需求
* 编写开发 Prompt
* 启动 Claude Code
* 等待开发完成
* 收集开发报告
* 编写 QA Prompt
* 启动 Codex
* 将 QA Finding 复制回 Claude
* 再次启动 QA
* 更新 Linear
* 创建或检查 Pull Request

v0.1 的目标是把这些操作压缩为：

```text
ticket-controller run RND-206
```

然后收到以下结果之一：

```text
READY_FOR_HUMAN_REVIEW
BLOCKED_REQUIREMENTS
BLOCKED_QA_EXHAUSTED
BLOCKED_ENVIRONMENT
BLOCKED_NEEDS_HUMAN
CANCELLED
```

---

## 2. System Principles

### 2.1 Deterministic actions must not be delegated to an LLM

能够由确定性代码完成的操作，必须由 Controller 完成。

包括：

* 创建 Worktree
* 创建 Branch
* 检查 Git Diff
* 检查 Commit
* 运行测试命令
* 读取 Exit Code
* Push Branch
* 创建 Pull Request
* 检查 Pull Request 是否存在
* 更新 Linear 状态
* 统计 Fix Attempt
* 校验 JSON Schema
* 清理 Worktree

Agent 只负责需要理解、推理和生成的工作。

### 2.2 Evidence over claims

Controller 不依赖 Developer Agent 的自我报告决定任务是否完成。

以下内容属于 Claim：

```text
I completed the implementation.
All tests passed.
The issue has been fixed.
```

以下内容属于 Evidence：

* Git Commit 存在
* Branch 相对 Base Branch 存在非空 Diff
* 测试命令 Exit Code 为 0
* CI Check 通过
* Pull Request 存在
* QA Verdict 通过 Schema 校验
* QA Verdict 为 PASS

Controller 只能依据 Evidence 推进状态。

### 2.3 Disposable runs instead of resumable runs

v0.1 不实现运行恢复。

每次执行都有独立的：

* `run_id`
* Worktree
* Branch
* 日志目录
* QA Verdict
* Pull Request

Controller 崩溃或运行失败后：

1. 将当前 Run 标记为 Aborted。
2. 执行 Cleanup。
3. 创建新的 Run。
4. 从头重新执行。

v0.1 接受由此产生的额外 Token 成本，以降低 Controller 的实现复杂度。

### 2.4 No false success

系统可以把任务标记为 Blocked，但不能在证据不足时标记为成功。

```text
Uncertain → BLOCKED
Malformed output → BLOCKED
Missing evidence → BLOCKED
QA timeout → BLOCKED
```

---

## 3. System Boundaries

### 3.1 Included in v0.1

v0.1 包含：

* 人工命令启动
* 从 Linear 读取 Issue
* Ticket Contract 校验
* Risk Tier 校验
* 创建独立 Run
* 创建 Git Worktree
* 创建 Feature Branch
* 调用 Claude Code Developer
* 确定性验证开发结果
* Push Feature Branch
* 由 Controller 创建 Pull Request
* 调用 Codex QA
* QA Verdict Schema 校验
* 最多两轮 Fix Loop
* 更新 Linear 宏观状态
* 输出运行摘要
* Cancel
* Cleanup

### 3.2 Explicitly excluded from v0.1

v0.1 不包含：

* Linear Webhook 自动触发
* 定时轮询 Linear
* Controller Resume
* 多 Ticket 并行
* 多 Agent 并行写代码
* 自动 Merge
* 自动生产部署
* 自动数据库迁移
* 自动修改生产数据
* 自动使用生产密钥
* 自动选择下一个 Ticket
* 自动创建产品需求
* Plane 归档同步
* 项目级编排
* Portfolio 级编排
* Agent 自主扩大 Scope

---

## 4. System Components

```text
Linear
  └── Ticket Contract and project overview

Local Python Controller
  ├── Ticket validation
  ├── Run management
  ├── Worktree management
  ├── Developer invocation
  ├── Deterministic verification
  ├── Pull Request creation
  ├── QA invocation
  ├── Fix Loop control
  └── Linear status updates

Claude Code
  └── Developer Agent

Codex
  └── Independent QA Agent

GitHub
  ├── Feature Branch
  ├── Commits
  ├── Pull Request
  ├── CI
  └── Engineering evidence
```

---

## 5. Source of Truth

### 5.1 Linear owns

Linear 是以下信息的 Source of Truth：

* Ticket identifier
* Goal
* Business context
* Scope
* Out of scope
* Acceptance criteria
* Priority
* Project
* Dependencies
* Risk tier
* Current macro status
* Cancellation decision

### 5.2 GitHub owns

GitHub 是以下信息的 Source of Truth：

* Branch
* Commit
* Diff
* Pull Request
* CI
* Test output
* QA evidence
* Review
* Merge status

### 5.3 Controller owns

Controller 是以下运行信息的 Source of Truth：

* Run ID
* Current internal state
* Worktree path
* Fix attempt count
* Agent process status
* Run logs
* Blocked reason
* Artifact paths

Controller 状态只用于运行观察和问题排查，不支持 Resume。

---

## 6. Supported Ticket Types

v0.1 只支持：

```text
R0 — Documentation, tests, analysis, read-only or very low-risk changes
R1 — Small, isolated, reversible code changes
```

v0.1 拒绝自动执行：

```text
R2 — Authentication, authorization, migration, architecture, cross-service changes
R3 — Production data, credentials, irreversible operations, infrastructure changes
```

遇到 R2 或 R3 时返回：

```text
BLOCKED_NEEDS_HUMAN
```

---

## 7. Ticket Contract

Linear Issue 必须能够被转换为 `ticket-spec.json`。

这是第一个承重契约。

### 7.1 Required fields

```yaml
schema_version: "1.0"

issue:
  key: RND-206
  title: Fix cross-tenant media access
  url: https://linear.app/...

repository:
  owner: example
  name: example-repository
  base_branch: main

goal: >
  Ensure that media belonging to another tenant cannot be retrieved.

scope:
  - Media download endpoint
  - Tenant-scoped media lookup
  - Regression tests

out_of_scope:
  - Media storage redesign
  - CDN migration
  - Authentication redesign

risk_tier: R1

acceptance_criteria:
  - id: AC-01
    statement: Authorized users can retrieve media belonging to their tenant.
    verification:
      type: automated
      command: pytest tests/media/test_access.py::test_authorized_access

  - id: AC-02
    statement: Cross-tenant media access returns HTTP 404.
    verification:
      type: automated
      command: pytest tests/media/test_access.py::test_cross_tenant_denied

required_checks:
  - git diff --check
  - pytest tests/media/
  - python -m compileall backend/app

constraints:
  max_fix_attempts: 2
  allow_database_migration: false
  allow_production_access: false
  allow_main_branch_push: false
```

### 7.2 Acceptance Criterion verification types

每条 Acceptance Criterion 必须包含 `verification`。

v0.1 支持：

#### Automated

通过自动化命令验证。

```yaml
verification:
  type: automated
  command: pytest tests/media/test_access.py
```

#### Query

通过检查脚本或查询验证。

```yaml
verification:
  type: query
  command: python scripts/check_data_integrity.py
```

#### Inspection

通过代码、文件或生成的 Artifact 检查。

```yaml
verification:
  type: inspection
  target: frontend/src/components/ErrorState.tsx
  evidence_required: Code review confirms separate forbidden and expired states.
```

### 7.3 Unsupported verification

以下 Ticket 不进入 v0.1 自动循环：

```yaml
verification:
  type: manual
```

需要人工判断的 Acceptance Criterion 返回：

```text
BLOCKED_REQUIREMENTS
```

### 7.4 Entry validation

Controller 必须拒绝以下 Ticket：

* 缺少 Goal
* Scope 为空
* 缺少 Out of scope
* 缺少 Acceptance criteria
* Acceptance Criterion 没有 ID
* Acceptance Criterion 没有 Verification
* Verification 类型不受支持
* 缺少 Repository
* Risk Tier 不是 R0 或 R1
* Base Branch 不存在
* Ticket 已取消
* Ticket 已经存在未清理的 Active Run

Controller 只执行结构校验，不使用 LLM 判断 Ticket 是否“写得好”。

---

## 8. Agent Responsibilities

## 8.1 Developer Agent

Developer Agent 使用 Claude Code。

它负责：

* 阅读 `ticket-spec.json`
* 阅读 Repository
* 理解相关代码
* 制定内部实现方案
* 修改代码
* 编写或修改测试
* 执行必要检查
* Commit 修改
* 输出非承重的 Developer Summary

它不得：

* Push 到 Main Branch
* Merge Pull Request
* 创建生产部署
* 修改 Linear
* 修改 Acceptance Criteria
* 扩大 Scope
* 执行数据库迁移
* 使用生产密钥
* 修改 Controller
* 创建 Pull Request

### 8.1.1 Developer Summary

Developer Summary 供人阅读，不参与 Controller 的状态判断。

建议格式：

```markdown
# Development Summary

## Implementation
- Added tenant filtering to the media lookup.
- Added regression tests for cross-tenant access.

## Files Changed
- backend/app/api/media.py
- tests/media/test_access.py

## Checks Run
- pytest tests/media/
- python -m compileall backend/app
- git diff --check

## Known Risks
- None
```

该报告可以不通过严格 Schema 校验。

---

## 8.2 QA Agent

QA Agent 使用 Codex。

它负责：

* 独立读取 Ticket Contract
* 检查 Base SHA 与 Head SHA 之间的 Diff
* 检查 Acceptance Criteria
* 运行相关测试
* 审查 Developer 编写的测试是否充分
* 检查 Scope 是否被扩大
* 检查是否存在回归风险
* 输出 `qa-verdict.json`

它不得：

* 修改生产代码
* 修改测试代码
* Commit
* Push
* 创建 Pull Request
* Merge Pull Request
* 修改 Linear
* 修改 Ticket Contract

如果测试覆盖不足，QA 必须输出 FAIL，并要求 Developer 补充测试。

---

## 9. QA Verdict Contract

`qa-verdict.json` 是第二个承重契约。

Controller 必须对它进行严格 JSON Schema 校验。

### 9.1 Structure

```json
{
  "schema_version": "1.0",
  "issue_key": "RND-206",
  "run_id": "rnd-206-20260720-001",
  "qa_attempt": 1,
  "verdict": "FAIL",
  "acceptance_criteria": [
    {
      "id": "AC-01",
      "status": "PASS",
      "evidence": [
        "pytest tests/media/test_access.py::test_authorized_access passed"
      ]
    },
    {
      "id": "AC-02",
      "status": "FAIL",
      "evidence": [
        "The media query is not scoped by tenant_id."
      ]
    }
  ],
  "findings": [
    {
      "id": "QA-001",
      "severity": "blocker",
      "type": "IMPLEMENTATION_DEFECT",
      "acceptance_criterion_id": "AC-02",
      "summary": "Cross-tenant access is still possible.",
      "evidence": {
        "file": "backend/app/api/media.py",
        "line": 184,
        "test": "test_cross_tenant_denied"
      },
      "required_fix": "Scope the media lookup by tenant_id before returning the record."
    }
  ],
  "non_blocking_comments": [],
  "recommended_next_state": "FIXING"
}
```

### 9.2 Allowed verdicts

```text
PASS
FAIL
BLOCKED
```

### 9.3 Verdict behavior

#### PASS

条件：

* 所有 Acceptance Criteria 均通过
* Required checks 均通过
* 没有 Blocker 或 Major Finding
* 测试覆盖被 QA 判断为充分
* 没有 Scope violation

Controller：

```text
→ READY_FOR_HUMAN_REVIEW
→ Linear: In Review
```

#### FAIL

条件：

* 实现不符合 Acceptance Criterion
* 测试不足
* 存在回归
* 存在 Blocker 或 Major Finding
* 存在 Scope violation

Controller：

```text
Fix attempt < 2
→ FIXING

Fix attempt >= 2
→ BLOCKED_QA_EXHAUSTED
```

#### BLOCKED

条件：

* Repository 信息不足
* QA 无法运行必要检查
* 环境缺少依赖
* Requirement 存在不可解决歧义
* 需要人工产品或技术决策

Controller：

```text
→ BLOCKED_ENVIRONMENT
或
→ BLOCKED_NEEDS_HUMAN
```

---

## 10. Test Ownership

v0.1 采用以下规则：

> Developer Agent 编写实现和测试；QA Agent 独立审查测试本身是否充分覆盖 Acceptance Criteria。

QA Agent 不直接修改或补充测试。

如果测试不足：

```json
{
  "verdict": "FAIL",
  "findings": [
    {
      "id": "QA-002",
      "severity": "major",
      "type": "INSUFFICIENT_TEST_COVERAGE",
      "acceptance_criterion_id": "AC-02",
      "summary": "The implementation has no regression test for cross-tenant access.",
      "required_fix": "Add a regression test proving cross-tenant access returns HTTP 404."
    }
  ]
}
```

Developer 根据 Finding 补充测试，然后重新进入 QA。

---

## 11. Controller State Machine

```text
CREATED
  ↓
VALIDATING_TICKET
  ├── invalid → BLOCKED_REQUIREMENTS
  └── valid
        ↓
CREATING_RUN
        ↓
DEVELOPING
        ├── process failure → BLOCKED_ENVIRONMENT
        └── completed
              ↓
VERIFYING_DEVELOPMENT
        ├── no commit → BLOCKED_ENVIRONMENT
        ├── empty diff → BLOCKED_ENVIRONMENT
        ├── test failure → BLOCKED_ENVIRONMENT
        └── verified
              ↓
CREATING_PULL_REQUEST
        ├── failure → BLOCKED_ENVIRONMENT
        └── created
              ↓
QA_RUNNING
        ├── PASS → READY_FOR_HUMAN_REVIEW
        ├── BLOCKED → BLOCKED
        └── FAIL
              ↓
FIXING
        ├── fix attempt ≤ 2 → VERIFYING_DEVELOPMENT
        └── fix attempt > 2 → BLOCKED_QA_EXHAUSTED
```

---

## 12. Disposable Run Model

### 12.1 Run ID

格式：

```text
<issue-key-lowercase>-<timestamp>-<short-id>
```

示例：

```text
rnd-206-20260720-163500-a7f2
```

### 12.2 Worktree

```text
.ticket-autopilot/worktrees/<run_id>/
```

### 12.3 Branch

```text
agent/<issue-key-lowercase>-<run_id>
```

示例：

```text
agent/rnd-206-rnd-206-20260720-163500-a7f2
```

实现时可以进一步缩短为：

```text
agent/rnd-206-20260720-a7f2
```

### 12.4 Run artifacts

```text
.ticket-autopilot/
├── config.yaml
├── schemas/
│   ├── ticket-spec.schema.json
│   └── qa-verdict.schema.json
├── runs/
│   └── <run_id>/
│       ├── state.json
│       ├── ticket-spec.json
│       ├── developer-summary.md
│       ├── qa-verdict-01.json
│       ├── qa-verdict-02.json
│       ├── qa-verdict-03.json
│       ├── controller.log
│       ├── developer.log
│       └── qa.log
└── worktrees/
    └── <run_id>/
```

### 12.5 Run state file

State file 用于：

* 查询当前状态
* 问题排查
* Cancel
* Cleanup
* 运行审计

它不用于 Resume。

```json
{
  "run_id": "rnd-206-20260720-163500-a7f2",
  "issue_key": "RND-206",
  "state": "QA_RUNNING",
  "worktree": ".ticket-autopilot/worktrees/rnd-206-20260720-163500-a7f2",
  "branch": "agent/rnd-206-20260720-a7f2",
  "base_sha": "abc123",
  "head_sha": "def456",
  "pull_request_number": 319,
  "qa_attempt": 2,
  "fix_attempt": 1,
  "created_at": "2026-07-20T16:35:00+09:00",
  "updated_at": "2026-07-20T16:52:00+09:00"
}
```

---

## 13. Controller CLI

### 13.1 Run

```bash
ticket-controller run RND-206
```

行为：

1. 读取 Linear Issue。
2. 生成并校验 Ticket Spec。
3. 创建 Run。
4. 更新 Linear 为 In Progress。
5. 执行开发、QA 和 Fix Loop。
6. 输出最终状态。

### 13.2 Status

```bash
ticket-controller status RND-206
```

或：

```bash
ticket-controller status --run-id rnd-206-20260720-163500-a7f2
```

输出：

* 当前状态
* 当前 Agent
* Worktree
* Branch
* Pull Request
* Fix Attempt
* 最后更新时间
* Blocked 原因

### 13.3 Cancel

```bash
ticket-controller cancel RND-206
```

行为：

* 停止当前 Agent 子进程
* 将 Run 标记为 CANCELLED
* 不自动删除远程证据
* 更新 Linear Comment
* 不将 Linear 自动改为 Done

### 13.4 Cleanup

```bash
ticket-controller cleanup RND-206
```

或：

```bash
ticket-controller cleanup --run-id <run_id>
```

行为：

* 删除本地 Worktree
* 删除本地 Feature Branch
* 对未合并的 Controller-created PR 执行预定义策略
* 删除远程 Feature Branch前必须确认它未合并
* 保留运行日志和 Verdict

### 13.5 No resume

以下命令不属于 v0.1：

```bash
ticket-controller resume RND-206
```

---

## 14. Deterministic Development Verification

Developer 完成后，Controller 必须验证：

### 14.1 Git evidence

* Worktree 存在
* 当前 Branch 正确
* Base SHA 已记录
* 至少存在一个新 Commit
* Head SHA 不等于 Base SHA
* Diff 非空
* Repository 没有未处理的 Merge Conflict
* Commit message 包含 Linear Issue Key

### 14.2 Test evidence

Controller 必须运行：

* Ticket 中每条 Automated / Query Verification
* `required_checks`
* Repository 预设的基础检查

所有 Exit Code 必须为 0。

### 14.3 Scope evidence

v0.1 可以支持可选配置：

```yaml
forbidden_paths:
  - infra/production/
  - secrets/
  - migrations/

max_changed_files: 20
```

命中 Forbidden Path 时返回：

```text
BLOCKED_NEEDS_HUMAN
```

### 14.4 Pull Request creation

只有确定性验证通过后，Controller 才可以：

1. Push Feature Branch。
2. 创建 Pull Request。
3. 写入 Linear Issue Key。
4. 写入 Run ID。
5. 写入 Acceptance Criteria Checklist。
6. 写入 Developer Summary。
7. 将 PR 设置为 Draft 或 Ready for Review，取决于配置。

Pull Request 标题格式：

```text
RND-206 fix: prevent cross-tenant media access
```

---

## 15. Fix Loop

当 QA Verdict 为 FAIL 时，Controller 将以下信息交给 Developer：

* 原始 `ticket-spec.json`
* 当前 `qa-verdict.json`
* Worktree Path
* Base SHA
* Current Head SHA
* Fix Attempt
* 当前 Diff 的读取方式

Controller 不重新概括 QA Finding。

Developer 指令必须明确：

```text
Fix only the findings listed in qa-verdict.json.

Do not expand scope.
Do not refactor unrelated code.
Do not modify the acceptance criteria.
Add or update tests when required by the findings.
Commit the fix when complete.
```

每轮修复后：

```text
Developer Fix
→ Deterministic Verification
→ Push
→ QA Re-run
```

最大修复次数：

```text
2
```

初次开发后的 QA 不计入 Fix Attempt。

因此最多出现：

```text
Initial Development
QA 1
Fix 1
QA 2
Fix 2
QA 3
```

QA 3 仍然 FAIL：

```text
BLOCKED_QA_EXHAUSTED
```

---

## 16. Blocked Categories

v0.1 只使用四类 Blocked。

### 16.1 BLOCKED_REQUIREMENTS

包括：

* Ticket Contract 不完整
* Acceptance Criterion 缺失 Verification
* 存在 Manual Verification
* Scope 不明确
* Risk Tier 不受支持

### 16.2 BLOCKED_QA_EXHAUSTED

包括：

* 两轮 Fix 后 QA 仍然 FAIL
* 同一个 Finding 反复出现
* 修复引入新的 Blocker

### 16.3 BLOCKED_ENVIRONMENT

包括：

* Agent CLI 无法启动
* 依赖安装失败
* 测试环境失败
* GitHub API 失败
* Linear API 失败
* Git Worktree 创建失败
* QA 输出无法通过 Schema 校验
* Agent 超时
* Agent 没有产生 Commit

### 16.4 BLOCKED_NEEDS_HUMAN

包括：

* 需要架构决策
* 需要修改 Scope
* 发现安全风险
* 命中 Forbidden Path
* 需要数据库迁移
* 需要生产权限
* 任务风险实际高于 R1
* QA 无法在现有证据下作出结论

---

## 17. Linear Status Mapping

v0.1 使用宏观状态，不把每次 Agent 切换同步到 Linear。

| Controller Event    | Linear Status                 |
| ------------------- | ----------------------------- |
| Run accepted        | In Progress                   |
| Developer running   | In Progress                   |
| QA running          | In Progress                   |
| Fixing              | In Progress                   |
| QA PASS             | In Review                     |
| Any blocked result  | Blocked                       |
| Cancelled           | Canceled 或原状态                 |
| PR merged           | 由 Linear GitHub Automation 处理 |
| Deployment complete | 不属于 v0.1                      |

Linear Comment 应保持简洁。

### Ready for Review comment

```markdown
## Ticket Autopilot Result

Status: Ready for human review  
Run: rnd-206-20260720-163500-a7f2  
Pull Request: #319  
Fix loops: 1  
Required checks: Passed  
AI QA: Passed  
Known blockers: None  

Engineering details are recorded in GitHub.
```

### Blocked comment

```markdown
## Ticket Autopilot Blocked

Category: QA_EXHAUSTED  
Run: rnd-206-20260720-163500-a7f2  
Fix loops: 2  
Last QA verdict: Failed  
Pull Request: #319  

Human decision is required before the ticket can continue.
```

---

## 18. Security Boundary

### 18.1 Git protection

* Main Branch 必须启用 Branch Protection 或 Ruleset。
* Agent 不得直接 Push Main。
* Agent 不得 Merge Pull Request。
* Pull Request 必须经过 Repo Owner Review 或记录明确的 Owner override。
* CI 和 AI QA 应作为 Required Checks。
* Repo Owner 可以显式授权 Controller push Feature Branch 或 Merge；授权必须包含 actor、action、approved_at 和 reason，且 Agent 不得自我授权。
* QA/视觉 pending 允许创建 Draft PR，但原始 pending/fail 证据必须保留，不得改写为 PASS。

### 18.2 Developer permissions

Developer 可以：

* 读取 Repository
* 修改 Worktree
* 运行测试
* Commit

Developer 不可以：

* Push Main
* Merge
* 修改 Linear
* 访问生产
* 使用生产密钥

### 18.3 QA permissions

QA 可以：

* 读取 Repository
* 读取 Diff
* 运行测试
* 写入 Run Artifact

QA 不可以：

* 修改代码
* Commit
* Push
* Merge
* 修改 Linear

### 18.4 Production boundary

v0.1 禁止：

* SSH 到生产服务器
* 读取生产数据库
* 修改生产数据
* 读取生产 Secret
* 执行生产部署
* 执行不可逆迁移

---

## 19. Configuration

建议配置文件：

```yaml
linear:
  ready_status: Ready for Development
  in_progress_status: In Progress
  in_review_status: In Review
  blocked_status: Blocked

github:
  repository: example/example-repository
  base_branch: main
  pr_draft: true

controller:
  max_fix_attempts: 2
  developer_timeout_minutes: 60
  qa_timeout_minutes: 30
  run_root: .ticket-autopilot/runs
  worktree_root: .ticket-autopilot/worktrees

developer:
  provider: claude-code

qa:
  provider: codex
  read_only: true

security:
  allow_main_push: false
  allow_merge: false
  allow_production: false
  allow_migrations: false
```

Credential 不得写入配置文件。

应从：

* Environment Variables
* Operating System Keychain
* GitHub CLI Authentication
* Linear Personal API Credential

中读取。

---

## 20. Suggested Implementation Structure

```text
ticket-controller/
├── pyproject.toml
├── README.md
├── src/
│   └── ticket_controller/
│       ├── cli.py
│       ├── controller.py
│       ├── state_machine.py
│       ├── models.py
│       ├── config.py
│       ├── exceptions.py
│       ├── adapters/
│       │   ├── linear.py
│       │   ├── github.py
│       │   ├── git.py
│       │   ├── claude.py
│       │   └── codex.py
│       ├── services/
│       │   ├── ticket_validator.py
│       │   ├── run_manager.py
│       │   ├── worktree_manager.py
│       │   ├── development_verifier.py
│       │   ├── qa_manager.py
│       │   └── cleanup_manager.py
│       └── schemas/
│           ├── ticket-spec.schema.json
│           └── qa-verdict.schema.json
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

---

## 21. Controller Exit Codes

建议：

| Exit Code | Meaning                   |
| --------: | ------------------------- |
|         0 | Ready for human review    |
|        10 | Blocked requirements      |
|        20 | Blocked QA exhausted      |
|        30 | Blocked environment       |
|        40 | Blocked needs human       |
|        50 | Active run already exists |
|       130 | Cancelled                 |

---

## 22. v0.1 Functional Acceptance Criteria

### AC-V01

Given a valid R0 or R1 Linear Ticket, running:

```bash
ticket-controller run <ISSUE_KEY>
```

creates a unique Run, Worktree and Feature Branch.

### AC-V02

A Ticket missing any required Ticket Contract field is rejected before Developer invocation.

### AC-V03

Developer Agent cannot directly push to Main, authorize a remote action, or
merge a Pull Request. The repository owner can explicitly authorize the
Controller to push one Feature Branch or merge one Pull Request, with an audit
record retained.

### AC-V04

Controller does not treat Developer Summary as proof of completion.

### AC-V05

Controller verifies Commit, Diff and required command Exit Codes before creating a Pull Request.

### AC-V06

Controller creates the Pull Request rather than asking Developer Agent to create it.

### AC-V07

QA Agent receives the original Ticket Contract, current Diff reference and test evidence.

### AC-V08

QA output must pass the `qa-verdict.json` Schema before Controller uses it.

### AC-V09

A QA FAIL triggers a narrowly scoped Fix Task containing the original QA Finding.

### AC-V10

Controller runs no more than two automatic Fix Attempts.

### AC-V11

After QA PASS, Linear is updated to In Review and receives the Pull Request link.

### AC-V12

After repeated QA failure, Linear is updated to Blocked with category `QA_EXHAUSTED`.

### AC-V13

Controller supports:

```text
run
status
cancel
cleanup
```

### AC-V14

Controller does not support Resume.

### AC-V15

Cleanup removes disposable Worktree resources without deleting merged code or production data.

---

## 23. Required Test Scenarios

Implementation must include tests for:

### Happy path

```text
Valid Ticket
→ Developer completes
→ Verification passes
→ QA passes
→ Linear In Review
```

### One-fix path

```text
QA 1 fails
→ Developer fixes
→ QA 2 passes
```

### Exhausted path

```text
QA 1 fails
→ Fix 1
→ QA 2 fails
→ Fix 2
→ QA 3 fails
→ Blocked QA_EXHAUSTED
```

### Invalid Ticket

```text
Missing Acceptance Criteria
→ Blocked REQUIREMENTS
→ Developer not invoked
```

### Unsupported risk

```text
Risk R2
→ Blocked NEEDS_HUMAN
```

### Developer claim without evidence

```text
Developer says complete
→ No Commit
→ Blocked ENVIRONMENT
```

### Test failure

```text
Commit exists
→ Required check fails
→ PR not created
```

### Malformed QA output

```text
Codex output is not valid JSON
→ Schema validation fails
→ Blocked ENVIRONMENT
```

### Insufficient test coverage

```text
QA identifies missing regression test
→ FAIL
→ Developer adds test
→ QA reruns
```

### Cancellation

```text
Agent is running
→ cancel command
→ Process terminated
→ Run marked CANCELLED
```

### Cleanup

```text
Aborted Run
→ cleanup
→ Worktree removed
→ Logs retained
```

---

## 24. Pilot Success Criteria

v0.1 进入完成状态前，应使用三个真实、低风险 Ticket 进行试运行。

成功标准：

| Metric                                 |         Target |
| -------------------------------------- | -------------: |
| Valid Ticket successfully starts       |            3/3 |
| Manual prompt copying after start      |              0 |
| Machine-readable QA output             |           100% |
| False PASS                             |              0 |
| Main Branch direct push                |              0 |
| Production access                      |              0 |
| Tickets reaching In Review             |   At least 2/3 |
| Fix attempts per Ticket                |            ≤ 2 |
| Human intervention before final review | ≤ 1 per Ticket |
| Complete engineering evidence retained |           100% |

---

## 25. Completion Definition

Ticket Autopilot v0.1 is complete when:

1. The Controller can run locally through a Python CLI.
2. It can read and validate a Linear Ticket.
3. It can create a disposable Worktree and Branch.
4. It can invoke Claude Code for implementation.
5. It can deterministically verify the implementation.
6. It can create a GitHub Pull Request.
7. It can invoke Codex for independent QA.
8. It can execute up to two Fix Loops.
9. It can update Linear to In Review or Blocked.
10. It has successfully processed three real low-risk Tickets.
11. It has produced no false PASS and no unauthorized Main or production action.

---

## 26. Deferred to v0.2

The following capabilities are explicitly deferred:

* Resume interrupted Run
* Linear status-triggered automatic start
* Webhook authentication and replay handling
* Multi-Ticket queue
* Parallel Runs
* Persistent Controller service
* Automatic PR merge
* Staging deployment
* Production verification
* Plane archival
* Historical metrics dashboard
* Skill evolution based on failure patterns

---

## 27. Final Architecture Statement

Ticket Autopilot v0.1 is not a general-purpose multi-agent platform.

It is a narrowly scoped experiment designed to answer one question:

> Can a structured Linear Ticket be transformed into a tested, independently reviewed GitHub Pull Request through a bounded Developer–QA–Fix loop, without manual prompt copying and without sacrificing evidence quality or security boundaries?

The v0.1 architecture is therefore:

```text
Linear Ticket
      ↓
Manual Controller Start
      ↓
Disposable Git Run
      ↓
Claude Development
      ↓
Deterministic Verification
      ↓
Controller-created Pull Request
      ↓
Codex Independent QA
      ↓
Maximum Two Fix Loops
      ↓
Linear In Review or Blocked
      ↓
Human Review and Merge
```

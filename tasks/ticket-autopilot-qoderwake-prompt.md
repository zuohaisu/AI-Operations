# Ticket Autopilot — QoderWake Workflow 创建提示词

> 用途：把这段提示词交给 QoderWake（CN 本地实例），让它创建一个能跑通
> 「工单 → 计划 → 开发 → 确定性验证 → 独立 QA → 有界修复 → PR → 回写状态」
> 闭环的 WakerFlow / 自动任务。
> 锚定来源：`specs/Ticket Autopilot v0.1 Specification.md` 与
> `src/ticket_autopilot/workflows/ticket-pipeline.yaml`。

---

## 一、一句话目标（North Star）

把一张**结构化**工单（ticket-spec）自动跑成「已通过确定性验证 + 独立 QA 门禁」的
Pull Request，并把结果回写到工单系统。每一环只认**证据**，不认自述。

闭环：`Ticket → 计划 → 开发 → 确定性验证 → 独立 QA → 有界修复循环 → 创建 PR → 回写工单状态`

---

## 二、工作空间与触发

- **工作空间来源**：本地目录（指定目标仓库路径，例如 `/path/to/target-repo`）。
- **触发方式**（按 QoderWake 最佳实践：**先手动验证成功路径+失败路径，再开触发**）：
  - 试点期：手动对话任务，传入一份 `ticket-spec.json`，先跑通。
  - 接真实工单源：GitHub Issue/Push/PR 事件、或 Linear 工单事件、或 API POST（用你自己的代码把 Plane/Linear → QoderWake API 桥接）。
- **试点建议**：先用一个本地样例仓库 + 一份样例 `ticket-spec.json` 跑通最小闭环，
  再接真实工单系统。不要一开始就开自动触发。

---

## 三、输入契约：`ticket-spec.json`（第一承重契约）

每个工单必须能转成如下结构（Controller 只做**结构校验**，不用 LLM 判断写得好不好）：

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
acceptance_criteria:
  - id: AC-01
    statement: Authorized users can retrieve media belonging to their tenant.
    verification:
      type: automated            # automated | query | inspection
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
  max_fix_attempts: 2            # 最大修复轮数（见第六节）
  allow_database_migration: false
  allow_production_access: false
  allow_main_branch_push: false
```

**入口校验（任一不满足 → 标记 BLOCKED_REQUIREMENTS，不进入循环）**：
缺少 `goal` / `scope` 为空 / 缺 `out_of_scope` / 缺 `acceptance_criteria` /
某 AC 无 `id` / 某 AC 无 `verification` / `verification.type` 为 `manual`（不支持）/
缺 `repository` / `risk_tier` 不是 R0 或 R1 / Base Branch 不存在 / 工单已取消 /
存在未清理的活跃 Run。

---

## 四、各阶段与 Waker 配置

> 每个 Waker 的工作空间都指向同一本地仓库目录；阶段间通过 `output_key` / 文件传递上下文。

### 阶段 1 — 工单接入与校验（Intake / Controller）
- **角色**：一个轻量「控制器」Waker（或步骤脚本）。
- **动作**：读取 `ticket-spec.json`，只做结构校验（见第三节）。
- **输出**：合法 `ticket-spec` + 生成 `run_id`（格式 `KEY-YYYYMMDD-HHMMSS-XXXX`）。
- **权限**：只读、最小权限。
- **失败**：结构不合法 → 写评论「BLOCKED_REQUIREMENTS」并停止。

### 阶段 2 — 计划（Planner）
- **角色**：自定义「Planner」Waker（LLM 驱动）。
- **输入**：`ticket-spec.json`。
- **动作**：阅读仓库、理解相关代码、写出**简洁实现计划**（改哪些文件、怎么验证）。
- **输出**：Plan 文本（仅人读，不参与状态判断）。

### 阶段 3 — 开发（Developer）
- **角色**：`Deven`（DevOps/开发）或自定义 Developer Waker，运行在**本地目录**。
- **输入**：Plan + `ticket-spec.json` + Worktree 路径（见约束）。
- **动作**：按 Plan 修改代码、编写/修改测试、运行必要检查、**Commit**。
- **输出**：Commit（含工单 Key 于 commit message）。
- **不得**：Push Main / Merge / 改工单系统 / 改 Acceptance Criteria / 扩大 Scope /
  做 DB 迁移 / 用生产密钥 / 改 Controller。

### 阶段 4 — 确定性验证（Verifier）
- **角色**：确定性步骤（工具/CLI，**不委托 LLM**）。
- **动作**：Controller 必须验证以下**证据**全部成立：
  - Git：Worktree 存在、当前 Branch 正确、至少 1 个新 Commit、Head SHA ≠ Base SHA、Diff 非空、无未解决 Merge Conflict。
  - 测试：运行每条 `automated/query` 型 AC 的 `command` + 全部 `required_checks`，**Exit Code 必须全为 0**。
  - Scope：若命中 `forbidden_paths`（如 `infra/production/`、`secrets/`、`migrations/`）→ BLOCKED_NEEDS_HUMAN；`max_changed_files` 超限同理。
- **输出**：验证通过 / 不通过（证据清单）。
- **失败**：无 Commit / 空 Diff / 测试失败 / 命中 forbidden path → BLOCKED_ENVIRONMENT（不假装成功）。

### 阶段 5 — 独立 QA（QA Waker，门禁）
- **角色**：`测试工程师`角色（**基于证据的报告**，不修代码、不跑单测修复）。
- **输入**：`ticket-spec.json` + Base↔Head 的 Diff + 开发者写的测试。
- **动作**：独立审查 Diff 是否满足每条 AC、审查开发者测试是否**充分覆盖** AC、检查 Scope 是否越界、检查回归风险；**只输出** `qa-verdict.json`（见第五节）。
- **不得**：改代码 / Commit / Push / Merge / 改工单系统 / 改 Contract。
- 若测试覆盖不足 → 必须输出 `FAIL` 并要求开发者补测试。

### 阶段 6 — 有界修复循环（Fix Loop）
- **触发**：QA Verdict = `FAIL` 且 `fix_attempt < max_fix_attempts`（默认 2）。
- **动作**：把原始 `ticket-spec.json` + 当前 `qa-verdict.json` + 当前 Diff 交回 Developer，**只修 findings**：
  `Fix only the findings listed in qa-verdict.json. Do not expand scope. Do not refactor unrelated code. Add/Update tests when required. Commit when complete.`
- **循环**：Developer 修复 → 确定性验证 → Push → QA 重跑（最多 2 轮）。
- **穷尽**：`fix_attempt >= 2` 仍 FAIL → `BLOCKED_QA_EXHAUSTED`，停止。
- **注意**：QoderWake 可能没有原生「最大重试 N 轮」配置，请把这段循环逻辑**写进 Developer/QA 的指令与条件判断里**（FAIL 则回到开发阶段，计数 +1，到上限则停止）。

### 阶段 7 — 创建 PR（Controller / Deven）
- **前置**：仅当确定性验证**与** QA 都通过后。
- **动作**（外部写入，**先留人工确认**，符合最佳实践）：
  1. Push Feature Branch；2. 创建 Pull Request；3. 标题格式 `RND-206 fix: <短描述>`；
  4. 写入 Issue Key / Run ID / AC Checklist / Developer Summary；5. 设为 Draft 或 Ready for Review（按配置）。

### 阶段 8 — 回写工单状态（Closer，唯一触碰工单系统的节点）
- **触发**：
  - QA PASS → 工单置 `In Review`，写「Ready for Review」评论（含 Run ID / PR 号 / Fix loops / 检查结果）。
  - 任何 Blocked → 工单置 `Blocked`，写「Blocked」评论（含类别 / Run ID / 最后 QA 结论 / 需人工决策）。
- **不得**：自动 Merge / 自动部署 / 改生产。

---

## 五、输出契约：`qa-verdict.json`（第二承重契约）

Controller 必须对其做**严格 JSON Schema 校验**。结构：

```json
{
  "schema_version": "1.0",
  "issue_key": "RND-206",
  "run_id": "rnd-206-20260720-001",
  "qa_attempt": 1,
  "verdict": "FAIL",            // PASS | FAIL | BLOCKED
  "acceptance_criteria": [
    {"id": "AC-01", "status": "PASS", "evidence": ["pytest ...::test_authorized_access passed"]},
    {"id": "AC-02", "status": "FAIL", "evidence": ["The media query is not scoped by tenant_id."]}
  ],
  "findings": [
    {"id": "QA-001", "severity": "blocker", "type": "IMPLEMENTATION_DEFECT",
     "acceptance_criterion_id": "AC-02", "summary": "Cross-tenant access still possible.",
     "evidence": {"file": "backend/app/api/media.py", "line": 184, "test": "test_cross_tenant_denied"},
     "required_fix": "Scope the media lookup by tenant_id before returning the record."}
  ],
  "non_blocking_comments": [],
  "recommended_next_state": "FIXING"
}
```

**Verdict 行为**：
- `PASS`：所有 AC 通过、无 Blocker/Major、测试充分、无 Scope 越界 → 进阶段 7/8。
- `FAIL`：实现不符 / 测试不足 / 回归 / 越界 → 进阶段 6（未穷尽）或 `BLOCKED_QA_EXHAUSTED`。
- `BLOCKED`：仓库信息不足 / 环境缺依赖 / 需求歧义 / 需人工决策 → `BLOCKED_ENVIRONMENT` 或 `BLOCKED_NEEDS_HUMAN`。

---

## 六、硬性约束（必须写进每个 Waker 的系统提示）

1. **确定性动作不委托 LLM**：创建 Worktree/Branch、查 Git Diff/Commit、跑测试、读 Exit Code、Push、建 PR、查 PR 是否存在、更新工单状态、统计修复次数、校验 JSON Schema、清理 Worktree —— 全部由工具/脚本完成。
2. **只认证据不认自述**：Controller 只依据「Commit 存在 / Diff 非空 / 测试 Exit 0 / PR 存在 / QA Schema 通过且=PASS」推进；`I completed it` / `All tests passed` 这类自述**不算**完成证据。
3. **不实现 Resume**：崩溃即标记 Aborted → Cleanup → 新 Run 从头重跑（接受额外 Token 成本换低复杂度）。
4. **不虚假成功**：证据不足 / 输出畸形 / QA 超时 → 一律 BLOCKED，绝不标成功。
5. **外部写入留人工确认**：PR 创建、工单状态变更等外部副作用，先暂停等人工确认（QoderWake 最佳实践，也符合 §18 安全边界）。
6. **权限边界**：不 Push Main、不 Merge、不 Production 访问、不用生产密钥、不做 DB 迁移、不扩大 Scope、不自动选择下一个 Ticket。

---

## 七、闭环状态机（简版）

```text
CREATED → VALIDATING_TICKET
  invalid → BLOCKED_REQUIREMENTS
  valid → CREATING_RUN → DEVELOPING
    process failure → BLOCKED_ENVIRONMENT
    completed → VERIFYING_DEVELOPMENT
      no commit / empty diff / test fail → BLOCKED_ENVIRONMENT
      verified → QA
        PASS → READY_FOR_HUMAN_REVIEW → (PR + 工单 In Review)
        FAIL & fix<2 → FIXING → DEVELOPING
        FAIL & fix>=2 → BLOCKED_QA_EXHAUSTED
        BLOCKED → BLOCKED_ENVIRONMENT / BLOCKED_NEEDS_HUMAN
```

---

## 八、试点验收标准（"跑通"的定义）

用 1 个低风险样例仓库 + 1 份样例 `ticket-spec.json` 验证以下四类场景全部符合预期：

1. **Happy path**：开发→验证→QA PASS→建 PR→工单置 In Review。
2. **One-fix path**：QA FAIL（测试不足）→ 修复 1 轮 → QA PASS → PR。
3. **Exhausted path**：QA 连续 FAIL 达 `max_fix_attempts` → 停止并标记 `BLOCKED_QA_EXHAUSTED`。
4. **Invalid ticket**：结构缺失 → 标记 `BLOCKED_REQUIREMENTS`，不进入循环。
5. **证据门禁**：开发者「声称完成」但无 Commit/测试失败 → 不前进、不标成功。

---

## 九、给 QoderWake 的实操建议（创建时照做）

- **先用可视化/自然语言建 WakerFlow**，手动跑一个样例，确认成功+失败路径，再开触发。
- **角色推荐**：
  - 计划 → 自定义 `Planner`（LLM）
  - 开发 → `Deven` 或自定义 `Developer`（本地目录，可写、可 Commit）
  - 验证 → 确定性步骤/工具（非 LLM）
  - QA → `测试工程师`（独立、只出 `qa-verdict.json`）
  - 关闭 → 自定义小 Waker/脚本（只回写工单状态）
- **循环**：把「FAIL 则回到开发、计数+1、到上限停止」写进阶段 5→3 的条件与指令里。
- **工单源**：Linear 原生支持；Plane 用 API 桥接（你自己的薄适配 → QoderWake API 触发）。
- **试点仓库**：建议用本仓库 `AI-Operations` 下一个最小子目录或一个独立 sandbox 仓库，避免误伤主分支（Main 必须开 Branch Protection）。

# Ticket Autopilot v0.1 — 开发任务票（中文草稿）

> 来源规格：`specs/Ticket Autopilot v0.1 Specification.md`（v0.1，2026-07-20）
> 项目宪章：`IDEA.md` / `AGENTS.md`（复用优先，先做能力审计 + 一个低风险垂直切片）
> 任务跟踪：Plane 项目 **Ticket Autopilot / AIO**（workspace `hspace`）
> 起草说明：本文件为任务票草稿，尚未推入 Plane。每张票对齐规格的具体章节，验收以「证据」为准（规格 §2.2）。

---

## 规格摘要（直接引用关键要求）

- **原始目标**（§1）：以一张结构化 Linear Issue 为输入，在隔离的 Git Worktree 中调用 Developer Agent 完成开发，再调用独立 QA Agent 验收；QA 失败时最多自动执行两轮修复；最终产出一张「已完成代码、已通过确定性测试、已通过独立 AI QA、等待人工 Review/Merge」的 GitHub PR。
- **核心技术原则**（§2）：
  - §2.1 确定性动作（建 worktree、建 branch、跑测试、读 exit code、push、建 PR、更新 Linear、清理）必须由 Controller 完成，不委托给 LLM。
  - §2.2 Controller 只能依据 **Evidence**（commit 存在 / diff 非空 / 测试 exit 0 / PR 存在 / QA verdict 通过 schema 且为 PASS）推进。
  - §2.3 一次性 Run 模型，不实现 Resume。
  - §2.4 可以 Blocked，不得在证据不足时标成功。
- **明确不做**（§3.2）：Webhook 触发、轮询、Resume、并行、自动 Merge、自动部署、自动迁移、自动改生产数据、自动选下一个 Ticket、Plane 归档同步、项目级/Portfolio 级编排。
- **支持的风险等级**（§6）：仅 R0（文档/测试/分析/只读/极低风险）与 R1（小而隔离、可逆的代码改动）；R2/R3 直接返回 `BLOCKED_NEEDS_HUMAN`。

---

## 技术栈与依赖（取自规格 §19 / §20）

- 语言：Python 3（本地 CLI），建议 `pyproject.toml` + `src/ticket_controller/` 包结构
- 开发者 Agent：Claude Code（§8.1）
- QA Agent：Codex，只读（§8.2）
- Ticket 源：Linear（字段 Source of Truth，§5.1）
- 代码/PR/证据：GitHub（§5.2）
- 隔离：Git Worktree + Feature Branch（§12）
- 凭证：环境变量 / OS Keychain / `gh` / Linear Personal API，不得写入配置文件（§19）
- 承重契约：`ticket-spec.json`（§7）、`qa-verdict.json`（§9），均需 JSON Schema 校验

---

## 开发任务票

### 阶段 0 — 前置：复用优先能力审计（gating）

#### [ ] T0：复用优先能力审计（前置卡点）
**描述**：在动手写 Controller 前，盘点现有能力能否闭合闭环的某些阶段：Linear/Plane 自动化、agent hooks、MCP、GitHub Actions、GitHub 原生集成。输出一份差距清单，记录「已具备的能力」与「只能靠自定义胶水/Controller 填补的缺口」。
**验收标准**：
- 产出审计文档（建议放 `research/` 或 `logs/`），逐阶段标注 已有能力 / 缺口
- 明确列出 v0.1 哪些阶段**不**需要自定义代码（如 Linear 状态同步、GitHub PR、CI 可由现有工具承担）
- 给出「最小胶水 + 必要自定义 Controller」的推荐范围
**参考**：`IDEA.md` 复用优先决策顺序（配置→薄胶水→小控制器）；规格 §0 对齐闸门（2026-07-22）
**文件**：`research/capability-audit.md`（或团队约定位置）

---

### 阶段 1 — 项目骨架与承重契约

#### [ ] T1：项目骨架与配置加载
**描述**：初始化 Python 包 `ticket_controller`，建立 `pyproject.toml`、包结构（§20）、`README.md`，实现 `config.yaml` 加载器（§19），凭证从环境变量/Keychain 读取，不落地明文。
**验收标准**：
- `pyproject.toml` 可 `pip install -e .`，包可导入
- `config.py` 能加载 §19 的示例配置（linear/github/controller/developer/qa/security 各段）
- 凭证字段（token）从环境变量读取，配置文件中无明文密钥
**参考**：§19 Configuration、§20 Suggested Implementation Structure
**文件**：`ticket-controller/pyproject.toml`、`src/ticket_controller/config.py`、`src/ticket_controller/cli.py`(占位)

#### [ ] T2：数据模型与两个契约 Schema
**描述**：定义 `ticket-spec.json` 与 `qa-verdict.json` 的 JSON Schema（§7.1、§9.1），并实现 `models.py` 的对应数据类。
**验收标准**：
- `schemas/ticket-spec.schema.json` 覆盖 §7.1 全部必填字段（issue.key/title/url、repository、goal、scope、out_of_scope、risk_tier、acceptance_criteria[含 id/statement/verification]、required_checks、constraints）
- `schemas/qa-verdict.schema.json` 覆盖 §9.1（schema_version、issue_key、run_id、qa_attempt、verdict、acceptance_criteria[]、findings[]、recommended_next_state），verdict 枚举 PASS/FAIL/BLOCKED
- `models.py` 提供可实例化的数据类，字段与 schema 一一对应
**参考**：§7 Ticket Contract、§9 QA Verdict Contract
**文件**：`src/ticket_controller/schemas/*.schema.json`、`src/ticket_controller/models.py`

#### [ ] T3：契约校验器
**描述**：实现两个契约的严格 JSON Schema 校验函数，供 Controller 在入口与 QA 产出后使用。
**验收标准**：
- 对合法 `ticket-spec.json` 返回通过；缺失必填字段/AC 无 id/无 verification/verification 类型非法 → 明确报错
- 对合法 `qa-verdict.json` 返回通过；非法 JSON 或字段不符 → 明确报错（对应 §9.3 的 BLOCKED 分支）
**参考**：§7.4 Entry validation、§9、AC-V08
**文件**：`src/ticket_controller/services/ticket_validator.py`（含 schema 校验部分）

---

### 阶段 2 — Ticket 接入与校验

#### [ ] T4：Linear Adapter（读取 Issue → ticket-spec）
**描述**：实现 `adapters/linear.py`，从 Linear 读取 Issue 并映射为 `ticket-spec.json`（§5.1、§7）。仅做结构化读取与字段映射，不做 LLM 判断。
**验收标准**：
- 给定 Issue Key，能拉取 Goal/Scope/Out of scope/Acceptance criteria/Priority/Risk tier/Repository 等字段
- 输出符合 T2 schema 的 `ticket-spec.json`
- 对缺失字段只做结构透传，不做「写得好不好」的判断
**参考**：§5.1、§7.1
**文件**：`src/ticket_controller/adapters/linear.py`

#### [ ] T5：Ticket 入口校验（含风险分级）
**描述**：实现入口校验（§7.4），拒绝不合规 Ticket，且 R2/R3 风险直接返回 `BLOCKED_NEEDS_HUMAN`（§6）。
**验收标准**：
- 缺 Goal / Scope 空 / 缺 Out of scope / 缺 AC / AC 无 id / AC 无 verification / verification 类型不受支持 / 缺 Repository / Risk 非 R0/R1 / Base Branch 不存在 / Ticket 已取消 / 存在未清理 Active Run → 拒绝并返回对应 `BLOCKED_*`（§7.4、§16）
- R0/R1 通过；R2/R3 → `BLOCKED_NEEDS_HUMAN`
- 纯结构校验，不调用 LLM 判断 Ticket 质量
**参考**：§6、§7.4、§16、AC-V02
**文件**：`src/ticket_controller/services/ticket_validator.py`

---

### 阶段 3 — Run 与 Worktree 管理（确定性）

#### [ ] T6：Run Manager（一次性 Run 模型）
**描述**：实现 Run 生命周期管理（§12）：生成 `run_id`、创建 `runs/<run_id>/` 与 `state.json`、记录 base/head SHA、fix/qa attempt、blocked 原因。明确「不 Resume」（§2.3、§13.5）。
**验收标准**：
- `run_id` 格式 `<issue-key-lowercase>-<timestamp>-<short-id>`（§12.1）
- `state.json` 字段覆盖 §12.5（run_id/issue_key/state/worktree/branch/base_sha/head_sha/pr_number/qa_attempt/fix_attempt/时间戳）
- 无 resume 命令；崩溃后标记 Aborted + Cleanup + 新建 Run
**参考**：§2.3、§12、§13.5、AC-V14
**文件**：`src/ticket_controller/services/run_manager.py`

#### [ ] T7：Worktree Manager（建/清 worktree 与 branch）
**描述**：实现 Git Worktree 与 Feature Branch 的创建与清理（§12.2/§12.3、§13.4）。
**验收标准**：
- 创建 worktree 于 `.ticket-autopilot/worktrees/<run_id>/`
- 创建 branch `agent/<issue-key-lowercase>-<短id>`
- cleanup 删除本地 worktree + 本地 feature branch；删远程 branch 前确认未合并；保留运行日志与 verdict（§13.4）
**参考**：§12.2、§12.3、§13.4、AC-V15
**文件**：`src/ticket_controller/services/worktree_manager.py`、`adapters/git.py`

#### [ ] T8：Git Adapter（确定性证据采集）
**描述**：实现确定性 Git 操作（§14.1）：worktree 存在、当前 branch 正确、记录 base SHA、至少一个新 commit、head≠base、diff 非空、无未解决 merge conflict、commit message 含 Issue Key。
**验收标准**：
- 上述各项均有布尔/证据返回，供 Controller 判断（非 LLM 判断）
- 任一失败返回明确证据缺失原因
**参考**：§14.1、AC-V05
**文件**：`src/ticket_controller/adapters/git.py`

---

### 阶段 4 — 开发调用与确定性验证

#### [ ] T9：Developer Adapter（Claude Code 调用）
**描述**：实现 `adapters/claude.py`，在 worktree 中调用 Claude Code Developer（§8.1），传入 `ticket-spec.json`，收集 Developer Summary（§8.1.1，供人读，不参与状态判断）。
**验收标准**：
- 只把 `ticket-spec.json` + repo 交给 Developer；不要求 Developer 做 push/merge/改 Linear/改 AC/扩大 scope/迁移/用生产密钥/建 PR（§8.1 禁止项）
- 收集 Developer Summary 落盘 `developer-summary.md`，但 Controller 不把它当完成证据（AC-V04）
**参考**：§8.1、§8.1.1、AC-V04
**文件**：`src/ticket_controller/adapters/claude.py`

#### [ ] T10：确定性开发验证器
**描述**：Developer 完成后，Controller 运行 §14.2 的测试证据：每条 Automated/Query verification、`required_checks`、仓库预设基础检查，全部 exit code 必须为 0；可选 scope 证据（§14.3 forbidden_paths / max_changed_files）。
**验收标准**：
- 运行 ticket 中每条 automated/query verification + required_checks，断言 exit 0
- 命中 forbidden path → `BLOCKED_NEEDS_HUMAN`（§14.3）
- 无 commit / 空 diff / 测试失败 → `BLOCKED_ENVIRONMENT`（§11 VERIFYING_DEVELOPMENT 分支）
**参考**：§14、AC-V05
**文件**：`src/ticket_controller/services/development_verifier.py`

---

### 阶段 5 — Pull Request 创建（由 Controller 完成）

#### [ ] T11：GitHub Adapter + PR 创建
**描述**：仅当确定性验证通过后，由 Controller push feature branch 并创建 PR（§14.4、AC-V06）；写入 Issue Key、Run ID、AC Checklist、Developer Summary；PR 设为 Draft 或 Ready（按配置）。
**验收标准**：
- Controller 自己建 PR，而非让 Developer Agent 建（AC-V06）
- PR 标题格式 `RND-206 fix: prevent cross-tenant media access`（§14.4）
- 验证失败则不建 PR（§11 CREATING_PULL_REQUEST 失败分支 → BLOCKED_ENVIRONMENT）
- Main Branch 受保护，Agent 不得直推 Main（§18.1）
**参考**：§14.4、§18.1、AC-V06、AC-V03
**文件**：`src/ticket_controller/adapters/github.py`

---

### 阶段 6 — QA 与修复循环

#### [ ] T12：QA Adapter（Codex 调用，只读）
**描述**：实现 `adapters/codex.py`，调用 Codex 独立 QA（§8.2），传入原始 Ticket Contract、base→head diff 引用、测试证据；收集 `qa-verdict.json`。
**验收标准**：
- QA 只读：不得改生产代码/测试/commit/push/merge/改 Linear/改 Contract（§8.2 禁止项）
- 若测试覆盖不足，QA 必须输出 FAIL 并要求补测试（§8.2 末、§10）
- 产出 `qa-verdict.json` 落盘 `qa-verdict-0N.json`
**参考**：§8.2、§10、AC-V07
**文件**：`src/ticket_controller/adapters/codex.py`

#### [ ] T13：QA Verdict 校验与状态路由
**描述**：对 QA 产出先做严格 Schema 校验（AC-V08），再按 verdict 路由（§9.3）：PASS→`READY_FOR_HUMAN_REVIEW`；FAIL→FIXING（attempt<2）或 `BLOCKED_QA_EXHAUSTED`（≥2）；BLOCKED→`BLOCKED_ENVIRONMENT`/`BLOCKED_NEEDS_HUMAN`。
**验收标准**：
- 非法 JSON / 不过 schema → `BLOCKED_ENVIRONMENT`（§9.3、§16.3）
- PASS 条件满足才路由到 Ready（§9.3 PASS 全条件）
- 输出 verdict 必须通过 schema 才被使用（AC-V08）
**参考**：§9.3、§16、AC-V08
**文件**：`src/ticket_controller/services/qa_manager.py`

#### [ ] T14：修复循环控制器（最多两轮）
**描述**：FAIL 时把原始 `ticket-spec.json` + 当前 `qa-verdict.json` + worktree/SHA/fix attempt 交给 Developer，给明确的窄范围修复指令（§15）；每轮修复后 Deterministic Verify → Push → QA 重跑；最大 2 次（§15）。
**验收标准**：
- 修复指令明确「只修 findings、不扩大 scope、不改 AC、按需补测试、完成后 commit」（§15 指令模板）
- Controller 不重新概括 QA finding，直接透传
- 初始开发后 QA 不计入 fix attempt；最多 QA1→Fix1→QA2→Fix2→QA3，QA3 仍 FAIL → `BLOCKED_QA_EXHAUSTED`（§15、AC-V09/V10）
**参考**：§15、§16.2、AC-V09、AC-V10
**文件**：`src/ticket_controller/controller.py`（含 fix loop 编排）

---

### 阶段 7 — 状态同步与 CLI

#### [ ] T15：Linear 状态更新
**描述**：按 §17 宏观状态映射更新 Linear：Run accepted/开发/QA/Fixing → In Progress；QA PASS → In Review；任意 blocked → Blocked；Cancel → Canceled 或原状态。写入简洁 Comment（Ready for Review / Blocked 模板）。
**验收标准**：
- 不把每次 Agent 切换都同步 Linear（只用宏观状态，§17）
- Ready comment 含 Status/Run/PR/Fix loops/Checks/QA（§17 模板）
- Blocked comment 含 Category/Run/Fix loops/Last verdict/PR（§17 模板）
**参考**：§17、AC-V11、AC-V12
**文件**：`src/ticket_controller/adapters/linear.py`（状态更新部分）

#### [ ] T16：CLI（run / status / cancel / cleanup，无 resume）
**描述**：实现 §13 的 CLI：`run <KEY>`、`status <KEY|--run-id>`、`cancel <KEY>`、`cleanup <KEY|--run-id>`；**不实现** `resume`（§13.5）。
**验收标准**：
- `run`：读 Linear → 生成/校验 spec → 建 Run → 更新 In Progress → 跑开发/QA/Fix loop → 输出最终状态（§13.1）
- `status`：输出当前状态/Agent/worktree/branch/PR/fix attempt/更新时间/blocked 原因（§13.2）
- `cancel`：停 Agent 子进程 → 标 CANCELLED → 不自动删远程证据 → 更新 Linear Comment → 不改 Done（§13.3）
- `cleanup`：删本地 worktree/branch，按策略处理未合并 PR，删远程 branch 前确认未合并，保留日志与 verdict（§13.4）
- 无 resume 子命令（AC-V14）
**参考**：§13、AC-V13、AC-V14
**文件**：`src/ticket_controller/cli.py`

#### [ ] T17：Controller 编排器与状态机
**描述**：把上述服务串成 §11 的状态机：CREATED→VALIDATING_TICKET→CREATING_RUN→DEVELOPING→VERIFYING_DEVELOPMENT→CREATING_PULL_REQUEST→QA_RUNNING→(PASS→READY_FOR_HUMAN_REVIEW | FAIL→FIXING→…→BLOCKED_QA_EXHAUSTED)。退出码按 §21（0/10/20/30/40/50/130）。
**验收标准**：
- 状态机各分支与 §11 完全一致
- 退出码映射正确（§21）
- 任一确定性失败都落到对应 BLOCKED_*，不会「假成功」（§2.4）
**参考**：§11、§21、§2.4
**文件**：`src/ticket_controller/controller.py`、`state_machine.py`

---

### 阶段 8 — 测试与试点

#### [ ] T18：单元测试 + 集成测试（覆盖 §23 场景）
**描述**：为 §23 列出的全部测试场景写测试：Happy path、One-fix、Exhausted、Invalid Ticket、Unsupported risk、Developer claim without evidence、Test failure、Malformed QA output、Insufficient coverage、Cancellation、Cleanup。
**验收标准**：
- 每个场景都有可运行测试，且断言 Controller 的最终状态/退出码符合 §23
- 关键承重契约（ticket-spec / qa-verdict schema）有专门校验测试
**参考**：§22（AC-V01~V15）、§23
**文件**：`tests/unit/`、`tests/integration/`、`tests/fixtures/`

#### [ ] T19：三个真实低风险 Ticket 试运行
**描述**：用 3 个真实、低风险 Ticket 跑通 v0.1（§24/§25），核对试点成功指标。
**验收标准**：
- 3/3 有效 Ticket 成功启动；启动后零手动 prompt 复制
- 机器可读 QA 输出 100%；假 PASS = 0；直推 Main = 0；生产访问 = 0
- ≥2/3 到达 In Review；每 Ticket fix ≤2；最终 review 前人介入 ≤1；工程证据 100% 保留（§24 指标表）
**参考**：§24 Pilot Success Criteria、§25 Completion Definition
**文件**：试点记录（建议 `logs/` 或 Plane 内更新）

---

## 质量红线（强制）

- [ ] 确定性动作（建 worktree/branch、跑测试、读 exit code、push、建 PR、更新 Linear、清理）一律由 Controller 代码完成，不委托 LLM（§2.1）
- [ ] 只依据 Evidence 推进状态，绝不把 Developer 自述当完成证据（§2.2、AC-V04）
- [ ] 一次性 Run，不实现 Resume（§2.3、AC-V14）
- [ ] 证据不足只标 Blocked，不标成功（§2.4）
- [ ] 仅 R0/R1 自动执行；R2/R3 → `BLOCKED_NEEDS_HUMAN`（§6）
- [ ] 开发者/QA 权限边界严格分离（§18.2/§18.3）：Agent 不得直推 Main、不得 Merge、不得改 Linear、不得碰生产/生产密钥
- [ ] 凭证从环境变量/Keychain 读取，不写入配置文件（§19）
- [ ] 每个 ticket-spec 的 AC 必须带 verification，且类型 ∈ {automated, query, inspection}（§7.2/§7.3）

## 备注

- 本草稿尚未推入 Plane。建议落地方式：T0（能力审计）作为第一张票先开工；其余票可批量写入 AIO 项目（中文），替换/补充此前 5 张英文种子票（#1~#5）。
- 按 `AGENTS.md` 的复用优先原则，T0 完成后应据审计结果**收窄** T1~T17 的自定义代码范围——能用 Linear/Plane/GitHub Actions/MCP 闭合的阶段不写代码。

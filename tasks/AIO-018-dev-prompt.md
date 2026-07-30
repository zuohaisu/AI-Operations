# AIO-18 开发提示词（Developer Prompt）

> ⚡ **立即执行，不要询问用户重述意图。** 先完成只读 preflight；真正 blocker 写入 Run artifact 并返回 `BLOCKED_REQUIREMENTS` 或 `BLOCKED_NEEDS_HUMAN`，不得让 Planner 猜测缺失事实。

> 交给 Developer agent 执行。开始前必须读 `AGENTS.md`、Plane 原票、AIO-8 Plane Connector、AIO-10 ticket contract、AIO-17 Web 接口和现有 `tasks/` 命名结构，并先输出 `[Goal check]`。AIO-17 未 QA PASS 并合并时，本票必须保持 Blocked。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane workspace `hspace`）
- 工单：AIO-18「实现 Plane 未完成工单面板与 Prompt 解析生成」
- Plane issue id：`51d93e04-84a8-4802-9fad-e35ff61b29b6`
- 优先级：high｜风险：R1｜依赖：AIO-17、AIO-8、AIO-10
- Repository：`zuohaisu/AI-Operations`
- PM 决议：Plane v2 字段映射、接口语义和本票影响闭包已于 2026-07-31 明确；不得再仅因旧字段 `description`/`identifier` 为 `null` 返回 `BLOCKED_NEEDS_HUMAN`。若现有代码尚不能执行该映射，分类为本票拥有的 `IMPLEMENTATION_GAP_OWNED_BY_AIO18` 并在本票内修复。

## [Goal check]
本工作推进「Ticket intake / Plan」阶段，证据 = Web 页面只展示 Plane 未完成工单，用户选择工单后可确定性复用已有 Dev/QA Prompt，或只让 Planner 生成缺失部分并记录来源；任何失败都发生在 Developer 启动前。

## 第一性原理与复用要求
- 复用 AIO-17 的同一个 localhost Web 服务和配置，不新建第二个 server、daemon 或前端工程。
- 复用 AIO-8 Plane Connector 的鉴权/读取能力与 AIO-10 ticket contract；不得复制 HTTP client、绕过结构校验或让 LLM 猜 workspace/project/repository。
- Prompt 文件命名以仓库现有约定为准：`tasks/AIO-NNN-dev-prompt.md` 与 `tasks/AIO-NNN-acceptance-prompt.md`。例如 AIO-18 映射到 `AIO-018-*`。
- Planner 只填补缺失 Prompt，不得重写已有文件；生成物属于本 Run artifacts，不回写 `tasks/`。

## 实战经验门禁
- AIO-17/AIO-8/AIO-10 依赖必须用具体命令验证 Web/service/config、Plane Connector 和 ticket contract 能力；Plane 状态不是 readiness 证据。最近一次基线证据为 HEAD `5e22b39e57aa9ec74a145a1f2a5dc9263419f2ba`、`25 passed in 0.37s`、checked-at `2026-07-30T16:05:41Z`；Developer 必须在 dispatch 时重跑，不得把该历史结果当作永久新鲜证据：
  ```bash
  .venv/bin/python -m pytest tests/test_web_service.py tests/test_local_config.py tests/test_connector_plane.py tests/test_ticket_contract.py -q
  ```
- Ticket eligibility 除九字段结构外，还检查 impact closure、调用方/消费方/触发守卫、可执行依赖、属性型 AC、上游接口实测语义和全局串行资源声明；缺失即在 Planner/Developer 前 `BLOCKED_REQUIREMENTS`。
- 生成的 Dev/QA Prompt 必须带“立即执行” action envelope、repository invariants、ticket-owned Diff/dirty-tree 归因规则，以及 UI Ticket 的视觉证据门禁。
- Planner 不得把项目具体 guard 文件写入通用模板；具体文件只能来自本 Ticket 或 repository workflow。

## PM 批准的 Plane v2 接口契约
- 只读实测来源：`GET /api/v1/workspaces/hspace/projects/{project_id}/work-items/{work_item_id}/?expand=state,project`；issue id `51d93e04-84a8-4802-9fad-e35ff61b29b6`。
- Observed fields：旧 `description=null`、旧 `identifier=null`、`description_html=non-empty`、`description_stripped=non-empty`、`sequence_id=18`、`project.identifier=AIO`、`state.id=47d77f48-8da6-4b8f-adf9-476def8d0f97`、`state.group=started`；checked-at `2026-07-30T15:43:04.884752Z`。
- Semantic mapping：
  - `issue_key = project.identifier + "-" + sequence_id`，本票确定为 `AIO-18`；禁止从 title 猜 identifier。
  - `description_html` 是结构化契约来源，必须确定性转换为保留 headings、lists、code blocks 的 Markdown 后交给 ticket-contract parser。
  - `description_stripped` 仅用于列表预览、搜索和空值判断，不得作为会丢失章节结构的契约解析输入。
  - `state.id` 作为来源 ID 保留；未完成过滤使用 `state.group`，不能使用本地化状态名。
  - Plane I/O 使用 `/work-items/`；旧 `/issues/` 兼容路径不得成为 AIO-18 的主读取路径。
- 有效 v2 payload 中旧字段为 `null` 是兼容性输入，不是缺失人类事实；只有 `description_html` 无法转换为有效契约、project/sequence/state 语义仍不明确，或原票确实缺承重内容时才可 `BLOCKED_NEEDS_HUMAN`。

## 影响闭包与串行资源
- Changed surface：`src/ticket_autopilot/connectors/plane.py`、ticket-contract normalization/preflight、AIO-17 Web Ticket API/UI、Prompt resolver、对应 fixtures/tests。
- Callers/consumers：identifier lookup、issue list/detail、`map_plane_issue`/preflight、eligibility gate、Prompt artifact preparation 和 Web source/status rendering；Developer 必须用 `rg` 再确认实际调用点。
- Triggered guards/contracts：Plane connector tests、ticket-contract tests、Web ticket/status filter tests、Prompt resolver call-count/content-preservation tests 和完整回归。
- Mandatory companion change：保持 main 为绿所必需的 Connector/contract fixture 和测试更新属于 AIO-18，不得推迟到未来票。
- Global serial resources：
  - 复用 AIO-17 owned service `127.0.0.1:8765`，不得绑定第二个固定端口或启动第二套 server。
  - repository `zuohaisu/AI-Operations` 同时最多一个 active Run；dispatch 时重新检查 freshness。

## In scope
- Web API/UI 读取并展示当前 Plane 项目的未完成 Ticket；以 Plane state group 排除 `completed`、`cancelled`，不靠中文/英文状态名硬猜。
- 列表与详情至少显示由 `project.identifier + sequence_id` 形成的 identifier、title、state、priority、risk/eligibility、Prompt availability/source，并支持显式刷新。
- 将 Plane Connector 的 AIO-18 读取路径迁移到 `/work-items/`，实现上述 v2 normalization；保留 raw source/provenance，禁止用 title 或 UI 文案补造字段。
- 点击 Run 前执行资格判断：Ticket identifier/项目匹配、未完成、ticket contract 合格、当前没有 active Run。
- Prompt resolver 按精确三位编号查找：
  - `tasks/<ISSUE-NNN>-dev-prompt.md`
  - `tasks/<ISSUE-NNN>-acceptance-prompt.md`
- 两份都存在：原样复制到 Run artifacts，Planner 调用 0 次，来源标记 `existing_file`。
- 只缺一份：保留已有 Prompt，只让 Planner 生成缺失角色；两个来源分别记录。
- 两份都缺失：Planner 在一次受约束的 planning 阶段生成两份非空、职责隔离的 Prompt，保存到 Run artifacts。
- Planner 输入只能使用 Plane 原票、ticket-spec、仓库只读上下文和 Prompt 模板约定；输出必须通过角色/非空/issue-key/边界校验。
- 若 Ticket 引用上游 API，Prompt 必须保留 observed fields、semantic assertion 和 checked-at；不能只写“依赖票已完成”。
- Planner 失败、超时、输出缺角色或不满足 schema 时进入 `HARD_BREAK_PLANNER`；Developer 调用次数必须为 0，页面显示可操作原因。
- 页面明确显示每份 Prompt 的来源和准备状态；本票只做到“Run ready”，不启动 Developer/QA。
- Ticket 列表、详情、Prompt source 和 Planner Hard Break 页面需要浏览器/视觉证据或明确 human visual gate；后端 API 测试不能单独证明页面可用。缺视觉结论时状态为 `HUMAN_VISUAL_REVIEW_PENDING`，可创建带 warning 的 Draft PR，但不得宣称 UI PASS。

## Out of scope
- 不执行 Developer、QA、Fix Loop、Git Commit，不创建 Worktree/PR，不写回 Plane 状态。
- 不在页面编辑 Prompt，不把 Planner 生成内容写入 `tasks/`。
- 不新增 Linear、GitHub Issues、多项目聚合、全文索引、数据库或复杂分页优化。
- 不实现并行 Run、自动选下一张票、WebSocket/SSE、远程访问或多用户权限。
- 不让 LLM 推断 API key、repository、Agent CLI 或缺失的承重 ticket contract 字段。
- 不改 `.github/workflows/**` 或保存真实 Secret。

## 验收标准
- AC-1：Plane 返回多种状态时，页面只展示未完成 Ticket，字段与 Connector 响应一致；`description=null`、`identifier=null` 但 v2 字段完整的 `started` payload 必须被规范化并保留，`completed`/`cancelled` 必须被拒绝。
- AC-2：Dev/acceptance Prompt 都存在时，Planner 调用次数为 0；两份内容原样进入 artifacts，来源为 existing file。
- AC-3：只缺一份时，Planner 只生成缺失角色；已有内容不变，页面分别显示来源。
- AC-4：两份都缺失时，artifacts 中生成两份非空、角色边界明确的 Prompt，仓库 `tasks/` 没有变化。
- AC-5：Planner 失败、超时或输出缺角色时，状态为 `HARD_BREAK_PLANNER`，Developer 不启动，页面可读到原因。
- AC-6：Done/Cancelled、由 project identifier/sequence 计算后仍不匹配、契约在 v2 normalization 后仍无效或已有 active Run 时，Run 请求被确定性拒绝，不创建第二个 Run；旧字段单独为 `null` 不是拒绝理由。

## 确定性验证
```bash
python3 -m pytest tests/test_web_tickets.py tests/test_prompt_resolver.py -q
python3 -m pytest -q
```

测试必须 mock Plane 与 Planner，并覆盖：
- completed/cancelled 的状态组过滤和字段保真；
- Plane v2 preservation：旧 `description`/`identifier` 为 `null`，但 `description_html`、`description_stripped`、`sequence_id`、expanded project/state 完整时仍解析为 `AIO-18`；
- Plane v2 counterexamples：缺 project identifier/sequence、HTML 转换后缺承重章节、未知 state group 时在 Planner 前安全拒绝；
- HTML→Markdown 转换保留 headings、lists、code blocks；`description_stripped` 不作为结构化 contract parser 的主输入；
- Connector 主读取路径为 `/work-items/`，不以 title 猜 identifier；
- 2/2、1/2、0/2 三种 Prompt 矩阵及精确 Planner call count；
- Prompt 内容 byte-for-byte 保留、来源 metadata 和 artifact 路径；
- Planner failure/timeout/malformed/role-missing；
- Ticket 不合格、identifier mismatch 和 singleton active Run；
- 所有拒绝路径的 Developer/QA 调用次数均为 0。
- 缺 impact closure/readiness check/behavioral AC/upstream semantics 时 Planner 调用为 0；
- 生成 Prompt 含 action envelope、repository invariants、attribution 和条件性 visual gate；
- 通用模板不出现 Ticket/项目专属文件路径。

任何覆盖已有 Prompt、修改 `tasks/`、错误展示已完成票、Planner 失败后启动 Developer、创建第二个 Web 服务或测试访问真实外部服务，均为 FAIL。

## 实施指引
1. 先画出 AIO-17 Web API 到 AIO-8/AIO-10 的调用边界；在现有服务增加最小 endpoint，不复制 Connector。
2. 先实现一个可独立单测的 Plane v2 normalization boundary，再将 state-group filter、issue-key→三位文件名映射、Prompt resolution 和 eligibility 设计为纯逻辑；preflight 不得要求“待本票修复的生产 Connector 已经预先具备该能力”。
3. 为 Run 准备阶段定义稳定的 artifact/metadata 结构，至少记录 issue key、两份 Prompt 路径、各自 source、Planner outcome 和 hard-break reason。
4. Planner 必须是可注入 adapter；测试使用 fake，不依赖本机 Agent CLI，不访问网络。
5. 在测试前后哈希/列出 `tasks/`，证明 resolver 和 Planner 不会修改规范 Prompt 文件。
6. 改动文件不超过 14，预期集中在既有 Web 层、Prompt resolver、静态页面和两份测试；Developer Agent 不自主 Push、Merge、部署或改 Plane。这是 Agent 权限边界，不得用于阻止 Repo Owner 显式要求 Controller push feature branch、创建 Draft PR、记录 override 或 merge。

## 完成定义、风险与回滚
- 六条 AC 均有自动化证据，相关回归全绿，独立 QA PASS。
- 风险：状态过滤错误会开发已完成 Ticket；文件名或 Planner 角色错误会把错误职责传给后续 Agent。
- 回滚：`git revert` Web Ticket API、Prompt resolver 和页面变更；Run artifacts 可保留诊断，Plane 与 `tasks/` 原始数据不变。
- Trigger：AIO-17 QA PASS 并合并后，PM 将 AIO-18 置 In Progress。
- Gate：人工 Review 状态组过滤、Prompt 查找顺序、Planner 输入/权限和 Hard Break 分类。
- Escalation：在应用本 Prompt 已批准的 v2 mapping 后，Plane project/sequence/state、Prompt 命名、承重 ticket contract 或 Planner 角色仍无法确定时，返回 `BLOCKED_NEEDS_HUMAN`；现有代码缺少已批准 mapping 时返回 `IMPLEMENTATION_GAP_OWNED_BY_AIO18` 并继续本票实现。

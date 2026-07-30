# AIO-18 验收提示词（Acceptance / QA Prompt）

> ⚡ **立即开始只读验收，不要先询问意图或请求只读许可。** 无法继续时，把 `BLOCKED`、证据和解阻条件写入 verdict；不得手工补 Prompt 或让用户重新解释任务。

> 交给独立 QA agent。全程只读：不得修改代码、Prompt、artifacts 或 Plane，不得调用真实 Planner/Developer/QA，也不得为了通过验收手工补齐缺失 Prompt。

## 任务身份与 Goal check
- 工单：AIO-18「实现 Plane 未完成工单面板与 Prompt 解析生成」
- Plane issue id：`51d93e04-84a8-4802-9fad-e35ff61b29b6`
- 风险：R1｜Repository：`zuohaisu/AI-Operations`
- `[Goal check]`：推进「Independent QA」，证据 = 独立验证未完成 Ticket 过滤、Prompt 复用/缺失生成矩阵、Planner Hard Break 和 Developer-before-ready 禁止规则。
- PM 决议：Plane v2 映射已于 2026-07-31 明确；QA 不得把生产代码尚未实现该映射误报为 `BLOCKED_NEEDS_HUMAN`，应分类为 `IMPLEMENTATION_GAP_OWNED_BY_AIO18`，并作为 AIO-18 实现缺陷验收。

## PM 批准的 Plane v2 验收基线
- 实测 endpoint：`GET /api/v1/workspaces/hspace/projects/{project_id}/work-items/{work_item_id}/?expand=state,project`。
- 实测 payload：旧 `description=null`、旧 `identifier=null`、`description_html=non-empty`、`description_stripped=non-empty`、`sequence_id=18`、`project.identifier=AIO`、`state.id=47d77f48-8da6-4b8f-adf9-476def8d0f97`、`state.group=started`；checked-at `2026-07-30T15:43:04.884752Z`。
- 规范语义：
  - `issue_key = project.identifier + "-" + sequence_id`，禁止从 title 猜测。
  - `description_html` 确定性转换为保留 headings/lists/code blocks 的 Markdown 后用于契约解析。
  - `description_stripped` 只用于预览、搜索和空值判断。
  - `state.id` 保留为来源 ID，过滤使用 `state.group`。
  - 主读取 API 使用 `/work-items/`。
- 旧字段为 `null` 但上述 v2 字段完整时必须 preservation PASS；缺 project identifier/sequence、HTML 转换后缺承重章节或未知 state group 是必须安全拒绝的 counterexample。
- Global serial resources：只复用 AIO-17 owned `127.0.0.1:8765`；`zuohaisu/AI-Operations` 最多一个 active Run。

## 启动资格与真实性检查
1. 先回读 AIO-17 的 QA/merge 证据；未完成时本票应为 `BLOCKED`，不能通过在 AIO-18 内补做 Web 底座绕过依赖。
2. 读 Plane 原票、AIO-18 Developer Prompt、AIO-8/AIO-10 接口、当前 `tasks/` 命名结构和完整 diff。
3. 记录 `git status --short --branch`、base/head SHA、tracked/untracked 文件以及 `tasks/` 前后清单。
4. 所有 Plane、Planner、Developer、QA 必须是 fake/mock；任何真实外部请求或真实 Agent spawn 都是 BLOCKED/FAIL。
5. 执行 AIO-17/AIO-8/AIO-10 readiness checks，不以 Plane state 代替能力证据。最近一次参考结果为 HEAD `5e22b39e57aa9ec74a145a1f2a5dc9263419f2ba`、`25 passed in 0.37s`、checked-at `2026-07-30T16:05:41Z`；必须重跑：
   ```bash
   .venv/bin/python -m pytest tests/test_web_service.py tests/test_local_config.py tests/test_connector_plane.py tests/test_ticket_contract.py -q
   ```
6. 冻结 ticket-owned Diff 与 pre-existing dirty paths；无法归因的回归返回 `BLOCKED_ATTRIBUTION`。
7. 影响闭包至少覆盖 Plane Connector、ticket-contract normalization/preflight、Web Ticket API/UI、Prompt resolver、实际 callers/consumers 和对应 guards/tests；为保持 main 为绿所需的 companion fixture/test 不得推迟到未来票。

## AC 证据矩阵
- AC-1：构造 backlog/unstarted/started/completed/cancelled 多状态响应；只展示前三类未完成票，identifier/title/state/priority 与 Connector 数据一致。必须包含旧 `description`/`identifier` 为 `null`、v2 字段完整的 preservation payload，以及缺 project identifier/sequence、HTML 契约无效、未知 state group 的 counterexamples。
- AC-2：放置两份现有 Prompt，验证 Planner=0 calls、artifacts 内容逐字节相同、两个 source 均为 `existing_file`。
- AC-3：分别测试只缺 Dev、只缺 acceptance；Planner 每次只生成一个指定角色，已有文件未改变，source metadata 正确。
- AC-4：两份都缺失时产生两份非空且职责分离的 artifact；`tasks/` 的文件列表、内容哈希和 Git 状态保持不变。
- AC-5：Planner exception、timeout、malformed output、missing role 分别进入 `HARD_BREAK_PLANNER`；Developer/QA/Commit 调用次数均为 0，UI/API 原样显示可操作原因且不泄露 Secret。
- AC-6：completed/cancelled、按 project identifier/sequence 计算后仍错误的 identifier/project、v2 normalization 后仍无效的 ticket contract、active Run 分别被拒绝；Run/Worktree/Agent 创建次数为 0。旧字段单独为 `null` 不得作为拒绝理由。invalid contract 必须包含语义失败样例：缺 impact closure、可执行 dependency、behavioral AC、upstream semantic evidence 或 serial-resource allocation。

## 必跑命令
```bash
python3 -m pytest tests/test_web_tickets.py tests/test_prompt_resolver.py -q
python3 -m pytest -q
```

必须记录命令、exit code、关键 case 和 mock call counts。除测试外还要检查：
- issue key 到文件名的零填充是确定性的，例如 `AIO-18 → AIO-018-*`；
- issue key 来自 expanded `project.identifier + sequence_id`，不来自 title 或本地化 UI 文案；
- `description_html` 转换后保留 headings、lists、code blocks；`description_stripped` 未被错误用作结构化 parser 主输入；
- Connector 的 AIO-18 主读取请求使用 `/work-items/`，state 过滤基于 expanded `state.group`；
- Prompt 查找不使用模糊匹配，不会误取其他工单或 archive 文件；
- Planner 生成物只进入 owned Run artifact 目录，路径不可逃逸 repository/Run 边界；
- 页面来源标签来自持久 metadata，不是前端猜测；
- status filter 使用 Plane state group，不硬编码单一语言的 Done/Cancelled 名称；
- API key、Planner 输入和异常日志没有 Secret。
- 生成的每份 Prompt 都以明确 action envelope 开场，并携带 repository invariants、归因纪律和条件性 visual gate。
- QA 只给判定与最小实现缺口，不建议推迟保持 main 为绿所必需的强制随附改动。

## 浏览器与视觉证据
- 记录 Ticket 列表、详情、existing/generated Prompt source、Planner Hard Break 的 URL、viewport 和截图或等价浏览器证据。
- 检查长标题、状态、优先级、Prompt source 和错误原因无明显遮挡/溢出，Run eligibility 与禁用原因可理解。
- 页面/DOM/API 不得出现完整 Secret；缺视觉证据且无人类 visual gate 时，UI 部分 `BLOCKED`。

## Scope 与回归检查
- 允许：在 AIO-17 Web 服务中增加 Ticket API/UI、Prompt resolver、Planner adapter/Run-ready artifacts、Plane v2 normalization/`work-items` mandatory companion change 和对应测试。
- 禁止：Developer/QA/Fix Loop、Commit、Worktree/PR、Plane 写回、Prompt 在线编辑、第二个 Web server、其他 ticket provider、远程/多用户能力。
- `.github/workflows/**`、真实 Secret 或超过 14 个改动文件属于 scope/security blocker，除非原票明确更新。
- AIO-17 lifecycle/config 测试必须继续通过；不能用破坏启动体验换取 Ticket 面板。

## Verdict 输出
```yaml
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-18
acceptance_criteria:
  - id: AC-1
    status: PASS | FAIL | BLOCKED
    evidence: <command/test/file:line>
planner_call_matrix:
  existing_both: 0
  missing_dev: 1
  missing_acceptance: 1
  missing_both: <actual>
downstream_call_counts:
  developer: 0
  qa: 0
  commit: 0
visual_evidence:
  status: PASS | FAIL | BLOCKED
  sources: []
findings:
  - id: QA-001
    severity: blocker | major | minor
    type: IMPLEMENTATION_DEFECT | INSUFFICIENT_TEST_COVERAGE | SCOPE_VIOLATION | SECURITY_VIOLATION
    summary: <observed fact>
    required_fix: <smallest acceptable fix>
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```

只有 AC-1～AC-6 全 PASS、两条测试命令为 0、`tasks/` 未被修改、所有 downstream call count 为 0 且无 blocker/major 时才可 PASS。QA 不得直接修复 finding。

若 preflight 或实现仍因旧 `description`/`identifier` 为 `null` 拒绝已完整的 v2 payload，verdict 应为 `FAIL`，finding type 为 `IMPLEMENTATION_DEFECT`；不得要求 PM 再次批准同一映射。只有应用上述映射后仍缺真实承重事实时，才推荐 `BLOCKED_NEEDS_HUMAN`。

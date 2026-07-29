# AIO-8 开发提示词 — 实现 Ticket/PR 连接器（Plane → YAML → 关单/建 PR）

> 本文件是交给**开发 agent** 的执行提示词。直接据此实现，无需再向人工确认设计方向（设计已锁定在工单与下方约束中）。

## 0. 重要背景纠正（必读，避免走偏）
- **AIO-8 来自 Plane，不是 Linear。** 工单编号 `AIO-8` 是 Plane 项目「Ticket Autopilot / AIO」的 issue #8（id `ad9c6997-55f0-4c0b-9e19-330e3cf27997`）。若有人让你去 Linear 找，请改到 Plane（workspace `hspace`，project `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）。
- **当前仓库架构已演进**，不要被 `specs/Ticket Autopilot v0.1 Specification.md` 误导：那份 spec 描述的是**旧的 `ticket_controller` 包 + Linear 工单源**；`tasks/ticket-autopilot-v0.1-tasklist.md`（T0–T19）也已过时（STALE）。
- **真实架构 = Plane 工单源 + `src/ticket_autopilot/` 包（Engine + Connector + handlers/workflows）**。以 Plane issues #1–#9 与 `src/ticket_autopilot/` 现有代码为唯一权威。

## 1. 工单原文摘录（AIO-8）
- **Goal：** 读 Plane 工单 → 翻译成 Engine YAML；闭环后关工单 + 建 GitHub PR（即架构图的 Ticket/PR 适配器）。
- **Scope In：** Plane 读、YAML 生成、关单、建 PR。
- **Scope Out：** Linear 支持（后续）。
- **Acceptance：** ① 给定 Plane 工单 ID，产出合法 YAML；② 闭环后工单状态更新 + PR 创建。
- **Verify：** 用一个真实 Plane 工单跑通 `读 → YAML → 关单 → 建PR`。
- **Depends on：** #2（schema/core）、#5（guardrails 保安全）。
- **Done：** connector 实现 + 集成测试绿。
- **Risk：** GitHub PR 权限；Plane API 限流 60/min。
- **Human：** Trigger=置 In Progress；Gate=PR review（此 connector 会建 PR，必须人 review 才合并）。

## 2. 当前代码事实（请勿重复造轮子）
- **Engine 已存在**：`src/ticket_autopilot/engine/engine.py` —— YAML 驱动的 DAG 解释器，顶层键 `version/name/vars/agents/params/nodes/edges/mock`（`engine.py` 第 69–131 行 `Engine.run` 解读这些键）。
- **Engine 入口**：`src/ticket_autopilot/engine/cli.py` →
  `python -m ticket_autopilot.engine run <workflow.yaml> --params '{"ticket_id":"..."}'`，`--mock` 可无密钥跑通（用 canned 输出）。
- **参考 workflow**：`src/ticket_autopilot/workflows/ticket-pipeline.yaml` —— 标准 4 节点 `plan→execute→verify→close`，agents 用 `llm/cli/llm/script`；含 verify→execute 的 loop 边（`when: nodes.verify.decision == 'reject'`, `max_retries`）与 verify→close 边（`when accept`）。你的连接器生成的 YAML **必须符合此结构**。
- **Plane API 客户端参考**：`src/ticket_autopilot/reference/ticket-pipeline/plane_client.py`（已验证的两点非显然事实：① Cloudflare 403 需浏览器 UA；② PATCH 状态用 `state` 字段而非 `state_id`；限流 60/min；`X-API-Key` 鉴权，token 从 env `PLANE_API_KEY` 或 `~/.workbuddy/mcp.json` 读取）。
- **已有「关单」handler**：`src/ticket_autopilot/engine/handlers/close_ticket.py` —— 调 `plane_client` 发评论 + 置 done。
- **Connector 占位**：`src/ticket_autopilot/connectors/__init__.py`（仅 docstring，待实现）。
- ⚠️ **`plane_client.py` 里 `PROJECT_ID` 硬编码为旧项目**（`5c5c7207-...`）。AIO 项目是 `d40168f5-5d44-4810-a39e-3b6558e9bf6e`、workspace `hspace`。**连接器必须参数化 workspace/project，不得沿用旧 ID。**

## 3. 范围边界
**In scope（你必须做）**
- Plane 读取：按 issue ID 拉取工单（标题 + 描述 + 状态）。
- YAML 生成：把 Plane 工单映射成合法 Engine workflow YAML。
- 关单：闭环后把 Plane 工单置 Done + 追加评论（整合既有 `close_ticket.py` 逻辑，避免重复）。
- 建 PR：闭环后创建 GitHub PR（feature branch，非 main，draft/ready-for-review，需人工 merge）。

**Out of scope（严禁做）**
- ❌ 不实现 Engine 本身（已存在）。
- ❌ 不实现 drivers（llm/cli/hermes/script，属 AIO-6）。
- ❌ 不实现 Codex 独立 QA（属 AIO-7）。
- ❌ 不实现安全护栏本体（属 AIO-5）—— 但本连接器必须**遵守**其约束：禁止 push main、必须人工 review。
- ❌ 不实现 Linear 支持（后续票）。

## 4. 交付物与 API 设计（建议结构，可微调）
在 `src/ticket_autopilot/connectors/` 下新增：

- **`plane.py`**
  - `fetch_issue(issue_id, *, workspace, project_id, api_key=None) -> dict`：复用 `plane_client.py` 的鉴权/浏览器 UA/限流写法，但参数化 `workspace`/`project_id`（默认 `hspace` / `d40168f5-...`）。
  - `build_workflow_yaml(issue: dict) -> dict`：把工单翻译成合法 Engine YAML（见 §5 映射规则）。
  - `close_ticket(issue_id, summary, *, workspace, project_id, api_key=None) -> dict`：置 Done + 评论（整合现有 `close_ticket.py` 逻辑）。
- **`github.py`**
  - `create_pr(*, repo, base, head, title, body, draft=True, token=None) -> dict`：创建 PR，**`head` 必须是 feature branch，绝不能是 `base`（main）**；返回 PR URL/编号。
- **（可选整合，需谨慎）**：把 `engine/handlers/close_ticket.py` 改为调用 `connectors.plane.close_ticket`，消除重复。此改动触及 engine 内部，**建议先把 connectors 实现为独立可用，再单独提一个小 PR 整合**；或保持 `close_ticket.py` 不变、由连接器直接复用 `plane_client`。两种皆可，但请勿在 AIO-8 主 PR 里做大范围重构。

### §5 YAML 映射规则（`build_workflow_yaml`）
- `version: "1.0"`；`name: ticket-<issue_id 或 sequence_id>`。
- `params.ticket_id` = 传入的 Plane issue ID。
- `agents`：复用 `ticket-pipeline.yaml` 的标准 4 agent（planner/executor/verifier/closer）定义。**其 driver 行为由 AIO-6/7 落地；本连接器只负责装配连线与注入 ticket 输入**。`--mock` 下用 canned 输出即可验证「合法」。
- `vars.max_retries`：沿用 `ticket-pipeline.yaml` 的 `5`。
- `nodes`/`edges`：`plan→execute→verify→close`；`verify→execute` 为 loop 边（`when: nodes.verify.decision == 'reject'`, `max_retries: ${vars.max_retries}`）；`verify→close`（`when: nodes.verify.decision == 'accept'`）。
- 把工单的 Goal/Scope/Acceptance 写入 `planner` 的 `system` 提示或 `vars`，使执行有上下文。
- **必须能通过** `python -m ticket_autopilot.engine run <生成的yaml> --mock --params '{"ticket_id":"<id>"}'` 跑通（mock 下无真实 Plane/GitHub 调用，仅验证 YAML 合法）。

## 6. 安全与护栏（硬性）
- PR 只允许建在 feature branch；任何路径都**不得 push/merge main**。
- 不写生产密钥到代码；密钥从 env（`PLANE_API_KEY`、GitHub token）读取，沿用 `plane_client` 的解析方式。
- 尊重 Plane 限流（60/min）；`fetch_issue`/`close_ticket` 失败需有清晰报错而非静默吞掉。
- 创建 PR 后**必须**保持 PR 为待 review 状态（draft 或 ready-for-review），由人工 merge；连接器**不得**自动 merge。

## 7. 验证方式（你自测用，也是交给 QA 的依据）
- **单测**：`pytest tests/`（建议 `tests/test_connector_plane.py`、`tests/test_connector_github.py`）—— 用 mock 拦截 Plane/GitHub 网络调用，覆盖：
  - `fetch_issue` 正确解析；UA/鉴权/限流写法与 `plane_client` 一致；参数化 workspace/project。
  - `build_workflow_yaml` 产出结构合法（能被 `engine.Engine(...)` 加载、节点/边引用一致、含必需字段）。
  - `create_pr` 拒绝 `head == base`、正确生成 PR 元数据。
  - `close_ticket` 调 Plane 置 Done + 评论。
- **端到端（真实，手动/CI-gated）**：用一个真实 Plane 工单跑通 `读 → YAML →（mock 闭环）→ 关单 → 建PR`；若环境变量缺失则跳过并标注。

## 8. Definition of Done
- [ ] `connectors/plane.py` + `connectors/github.py` 实现完成。
- [ ] 给定 Plane 工单 ID 能产出**合法 YAML**（用 `engine.run(mock=True)` 校验可加载可跑）。
- [ ] 闭环后工单状态更新为 Done + 评论；GitHub PR 在 feature branch 创建、非 main、待 review。
- [ ] 集成测试绿（mock 覆盖 + 真实 gated 可选）；无新 lint/类型错误。
- [ ] 未触碰 Engine/drivers/QA 本体；未实现 Linear。

## 9. 风险与回滚（来自工单）
- GitHub PR 权限：依赖 gh CLI / token；权限不足时清晰报错。
- Plane API 限流 60/min：连接器需有退避 / 清晰错误。
- 回滚：纯新增文件 + 可选小整合 PR，`git revert` 即可。

## 10. 关键文件指针
- `src/ticket_autopilot/connectors/__init__.py`
- `src/ticket_autopilot/engine/engine.py`、`engine/cli.py`
- `src/ticket_autopilot/workflows/ticket-pipeline.yaml`
- `src/ticket_autopilot/reference/ticket-pipeline/plane_client.py`
- `src/ticket_autopilot/engine/handlers/close_ticket.py`
- `specs/agent-ready-ticket-template.md`（工单描述结构参考：Goal/Scope/Acceptance/Verify）
- 既有测试：`src/ticket_autopilot/engine/tests/test_engine.py`（参照其 pytest 风格）

## 11. 人工触点
- **Trigger：** PM 把 AIO-8 置 In Progress 即开始。
- **Gate：** PR review（连接器会建 PR，**必须人工 review 才 merge**）。
- **Escalation：** 3 次失败重跑后升级人工。

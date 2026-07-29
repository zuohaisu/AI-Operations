# AI-Operations — Project Memory

## What this project is
Conceptually **Ticket Autopilot** — a lightweight local controller that turns a structured ticket into a verified, independently QA'd GitHub PR (spec: `specs/Ticket Autopilot v0.1 Specification.md`). Git repo folder temporarily stays `AI-Operations`. North Star per `AGENTS.md`: ticket-driven automated software delivery. Start with a reuse-first capability audit + one low-risk vertical slice (no custom platform).
- Team name is **VF/VFF** but is intentionally NOT used in this project (hard to pronounce).

## Plane project (task tracking)
- Workspace `hspace` (Plane Cloud), project **Ticket Autopilot / AIO**, ID `d40168f5-5d44-4810-a39e-3b6558e9bf6e`.
- URL: https://app.plane.so/hspace/projects/d40168f5-5d44-4810-a39e-3b6558e9bf6e/
- The Plane MCP **cannot create projects** — use the REST API. Full how-to + gotchas are in the daily log (2026-07-27.md). Key ones: create cycle needs `project_id` in body; work-item create ignores `state_id`/`label_ids`/`cycle_id` (set via PATCH with `state`/`labels`, and cycle via `POST /cycles/{cid}/cycle-issues/` `{"issues":[id]}`).

## Directory structure (finalized 2026-07-28)
- `src/ticket_autopilot/` — **the product package (Ticket Autopilot)**.
  - `engine/` — **Engine** (orchestration core; importable as `ticket_autopilot.engine`): `engine.py` (DAG + retry-loop interpreter), `drivers.py` (llm/cli/hermes/script executors + guardrails), `store.py` (run snapshots), `cli.py` (`python -m ticket_autopilot.engine`), `handlers/close_ticket.py` (only node touching Plane; reuses `reference/ticket-pipeline/plane_client.py`).
  - `connectors/` — **Connector layer** (glue to Linear/Plane/GitHub/Codex). Renamed from `adapters/` 2026-07-28 (user picked "Connector" over "Handler": Handler collides with engine's internal `handlers/` and is too granular).
  - `cli.py` / `schemas/` / `services/` — product CLI (`ticket-controller` entry = `ticket_autopilot.cli:main`), ticket-spec + qa-verdict JSON Schemas, validators/managers (scaffold).
  - `reference/ticket-pipeline/` — predecessor PoC (orchestrator.py, plane_client.py, dagu-poc/); reached by `close_ticket.py` via relative `../../reference/ticket-pipeline`.
  - `workflows/` — YAML defs (`ticket-pipeline.yaml`, `ticket-pipeline-hermes.yaml`).
  - `runs/` + `sandbox/` — runtime artifacts (gitignored; `sandbox/*` keep `.gitkeep`).
- `tooling/start-prompt/` — **parked** prompt-source + eval (`core/` `modules/` `platform/` `eval/`; `eval/build_v5.py` reads `core`/`modules` as siblings of `eval`).
- `tooling/codex-notification-setup/` — parked codex infra config.
- `specs/` `research/` `logs/` `tasks/` `tests/` — spec doc, research notes, goal-drift log, Chinese task list, top-level product tests.
- ⚠️ **STALE doc**: `tasks/ticket-autopilot-v0.1-tasklist.md` (T0–T19) describes the **OLD `ticket_controller` package** (Linear/GitHub/Claude/Codex adapters per the v0.1 spec) — **NOT** the current Engine + Connector architecture. Do NOT use it as architecture reference. The real architecture lives in Plane issues #1–#9 + `src/ticket_autopilot/`. AIO-2 ("定义并接通闭环工单工作流") is Plane issue #2, grounded in the new architecture.
- `pyproject.toml` (src-layout, console `ticket-controller` = `ticket_autopilot.cli:main`), `.gitignore` (`.ticket-autopilot/`, `runs/`, `worktrees/`, `sandbox/*`, `.env`).

## Naming convention (locked 2026-07-28, rationale preserved)
- **Product** = "Ticket Autopilot"; **Engine** = the orchestration core (`src/ticket_autopilot/engine/`); **Connector** = the glue layer (`src/ticket_autopilot/connectors/`, ex-`adapters/`). Legacy "Vivarium Forge Flow" / `vff` / `forge_flow` naming fully removed from code+docs on 2026-07-28.
- **Why "Connector" not "Handler"**: Handler = fine-grained single-step function, AND collides with engine's internal `engine/handlers/` (YAML `script` node step processors). Connector = precise interface-adaptation semantics, zero collision. Code already uses it (`adapters/` → `connectors/`).
- **Why Engine merged into the product package**: there were TWO things both named "Ticket Autopilot" — the standalone engine folder (ex Vivarium Forge Flow / `vff`) and the top-level product skeleton `src/ticket_autopilot/`. Decision: absorb the engine as `engine/` so the whole product = Engine + Connector + business services, eliminating the "two Ticket Autopilots" ambiguity.
- **Two easy-to-confuse `ticket-autopilot`**: `src/ticket_autopilot/` = source package; `.ticket-autopilot/` (in specs/tasklist) = runtime dotfolder (worktree/run dir), spec-defined and intentionally kept. They are NOT the same thing.
- **Engine role (one-liner)**: a declarative YAML-driven closed-loop agent orchestrator — reads a workflow YAML, builds a DAG, drives Plan→Execute→Verify→Close, auto-reruns Execute on Verify-reject up to `max_retries` (default 5), with strict CLI sandboxing. Ticket source is pluggable (Plane now, Linear/GitHub later).

## Future plan: open-source Ticket Autopilot
- Product lives in `src/ticket_autopilot/`; to open-source later, publish that package (Engine + Connector + reference) as a standalone GitHub repo, separate from this `AI-Operations` meta-repo.

## Conventions / preferences
- Reply in Chinese for this user; git write ops need explicit approval.
- Goal-drift log + mandatory [Goal check] line at start of each piece of work (see AGENTS.md).

## 工作方式约定（2026-07-28 明确）
- **PM agent 角色边界**：只做任务拆解 + 写 Plane 工单，**不写实现代码**；具体工作交执行 agent。
- **本项目 dogfood Engine 流程**：自动化 Engine 建成前，由用户**手动当 Engine**——读 Plane 工单 → 驱动执行 agent 跑 Plan→Execute→Verify→Close → 关单/建 PR。
- **Plane 工单格式** = `specs/agent-ready-ticket-template.md`（9 字段：标题/目标/范围边界/验收标准/验证方式/依赖/Done 定义/风险回滚/人工点位）。
- **AIO 提示词交付约定（扁平化 2026-07-28）**：每个 AIO 票的开发/验收提示词写成 `tasks/AIO-00<N>-dev-prompt.md` 与 `tasks/AIO-00<N>-acceptance-prompt.md`（单层文件、零填充 3 位、不分子目录，省文件夹）。`AIO-00<N>` 对应 Plane 项目 Ticket Autopilot/AIO 的 issue #<N>。两提示词格式锚定 AIO-002（`AIO-002-dev-prompt.md`/`AIO-002-acceptance-prompt.md`），含 [Goal check]、AC-1..、确定性验证命令、复用优先硬约束、禁止用旧 `tasks/ticket-autopilot-v0.1-tasklist.md` 作架构依据。非约定文件保留：`ticket-autopilot-qoderwake-prompt.md`（QoderWake 专用，待定是否并入）、`ticket-autopilot-v0.1-tasklist.md`（STALE，勿作架构依据）。目前已有提示词的票：#1/#2/#3/#4/#5/#6/#7/#8/#9（全部齐备，AIO-004 与 AIO-005 于 2026-07-28 晚补齐）。
- **归档规则（2026-07-29 终版）**：
  - *提示词*（`AIO-00<N>-{dev,acceptance}-prompt.md`）：仅当对应 Plane 票 `state_group=completed` 才进 `tasks/archive/`；started/unstarted 的票其提示词留在 active。曾误把 #1/#4/#6（started）提前归档，已退回 active。
  - *QA 验证产物*（`AIO-00<N>-qa-verdict.json`）：**最终结论 = pass/accept 即可进 archive**，独立于票的完成状态。判定字段：`verdict:"PASS"` / `decision:"accept"`。`AIO-005`(accept) 与 `AIO-008`(PASS) 均已归档；其余票暂无 qa-verdict 文件。
  - 当前 archive = #2/#3/#7/#8 提示词 + AIO-005/AIO-008 两个 qa-verdict；active = #1/#4/#5/#6/#9 提示词。
- **护栏边界（跨票）**：CLI 沙箱/只读/白名单逻辑在 `engine/drivers.py::cli_call`，实现雏形已存在；**增强**归 AIO-9（安全护栏），其余 AIO 票（如 AIO-6 drivers）只测/留不增强。
- **Agent 团队架构（已确认 2026-07-29）**：闭环角色映射 —— Plan = Codex CLI（WorkBuddy CLI 本机无二进制，改用 Codex CLI 兜底）；Execute(dev×2 备份) = Claude Code + 「pi」(pi 身份**仍未确认**)；Verify(QA×2 备份) = QoderWake CLI + Codex。**注意：Codex 同时承担 Plan 与 QA#2 两角色**（非独立工具、非严格"互为备份"）。缺口：#7 工单只写 Codex，要落实"2QA备份"需把 QoderWake CLI 也接进 Verify（扩 #7）。未启动票 #7/#8/#9 确认次序：#9 安全护栏 → #8 连接器 → #7 Codex QA。

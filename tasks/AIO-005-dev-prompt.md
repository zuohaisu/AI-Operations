# AIO-005 开发提示词 — 首个低风险垂直切片（执行票）

> **[Goal check]** 本工作推进闭环阶段「首个真实低风险垂直切片」——交付一份可复用的执行 Runbook + 证据契约，把 1 个真实 Plane 工单用纯复用能力端到端跑完闭环，并把每阶段证据写入 goal-drift 日志。

## 0. 工单来源纠正（必读）
- **AIO-5 实际在 Plane**，不在 Linear。项目 = `Ticket Autopilot / AIO`，issue **#5「首个低风险垂直切片」**，id `36bef6e6-0fb9-44f3-8920-e2b2a5dda0f3`，priority=high，state=unstarted，cycle=Cycle 1，assignee=Haisu。
- Linear 搜 "AIO"/"Autopilot" 均空。用户口语 "linear" = Plane 工单系统（与 AIO-1/2/3/6/7/8/9 一致）。
- **本票性质不同于 AIO-2/3/6/7/8/9**：它不是"建一个组件"的票，而是"吃自己狗粮"的**执行票**。交付物 = 选 1 个真实、低风险工单，用纯复用能力把它端到端跑完闭环，并把每阶段证据写进 goal-drift 日志。**不做新功能开发。**

## 1. AIO-5 原文（Plane 描述）
- **目标**：挑选一个真实、低风险的任务，仅用复用能力（不新建平台）端到端跑通闭环。
- **执行**：实现 → 确定性验证 → 独立 QA → 有界修复循环 → PR → 工单状态更新。
- **要求**：把每个阶段产生的证据记录在 goal-drift 日志中。

## 2. 当前真实能力盘点（决定本票怎么跑）
### 已就绪（可复用，禁止重建）
- 闭环定义：`AGENTS.md` / `IDEA.md`（AIO-2 已完成），含强制 `[Goal check]` 行。
- Engine：`src/ticket_autopilot/engine/engine.py`（YAML 驱动 DAG + reject→execute 重试循环，max_retries=5）；`python -m ticket_autopilot.engine run --mock` 无密钥跑通；`engine/tests/test_engine.py` **7 测全绿**（本次已复跑确认）。
- Plane MCP：**已连接**，可读/写工单、评论、状态（本次 `list-issues` 实测可用）。
- GitHub：`gh` CLI **已登录 zuohaisu**，remote=`https://github.com/zuohaisu/AI-Operations.git` → PR 可建。
- 证据模板：`logs/goal-drift.md` 末尾「Entry template」（本票必须用此格式）。
- 工单模板：`specs/agent-ready-ticket-template.md`（含「Worked example (low-risk vertical slice)」可作选型参考）。

### 尚未建成（本票**只记录缺口，不实现**）
- AIO-8 Plane→YAML→关单/建PR 连接器（未建）→ 本票用 Plane MCP 手动读/写 + `gh` 手动建 PR 代替自动连接器。
- AIO-7 Codex 独立 QA 连接器（未建）→ 本票用 Engine `verify` 节点（driver: llm/hermes）或人工独立复核代替。
- AIO-9 安全护栏（未强制）→ 本票遵守"只读/不越权"手动纪律。
- AIO-6 drivers 专属测试（未建）→ 本票不依赖也不补。

## 3. 范围边界
### In scope
- 选 1 个真实、低风险、可 PR 的工单（候选见 §5）。
- 按 6 阶段跑完闭环：实现 → 确定性验证 → 独立 QA → 有界修复循环 → PR → 工单状态更新。
- 每阶段在 `logs/goal-drift.md` 用 Entry template 写证据（含 `[Goal check]` 行）。
- 记录过程中暴露的、应由 AIO-6/7/8/9 填补的胶水缺口（写入 goal-drift，不在此票实现）。

### Out of scope（硬约束，越界即 FAIL）
- 不新建任何平台 / 框架 / 引擎功能。
- 不实现 AIO-8 连接器、AIO-7 Codex QA、AIO-9 护栏、AIO-6 测试（这些是独立票）。
- 不修改 Engine 核心逻辑、不改动 `ticket-pipeline.yaml` 的节点结构。
- 不自动 push main、不自动 merge。

## 4. 选型标准（对齐 agent-ready-ticket-template 的 Worked example）
候选工单须满足：① 单一可交付结果；② 验收清晰可机检；③ 无新平台；④ 可逆（git revert 即可）；⑤ 有确定性验证命令；⑥ 真实存在缺口（不是重复造已存在的产物）。

> 已核实**非**缺口（勿重复选）：`CONTRIBUTING.md`、`.github/PULL_REQUEST_TEMPLATE.md`、`docs/closed-loop-workflow.md`、`README.md` 均**已存在且内容当前**（AIO-3 脚手架已交付）。`engine.py:184` 的 `raise WorkflowError("unknown driver")` 是单一终守卫，**无重复死代码**（早前"184-185 重复"记录已过时）。

## 5. 候选工单（推荐 + 备选）
### ★ 推荐候选：新增 GitHub Actions CI 工作流，在 push/PR 时跑 Engine 测试
- **真实缺口**：`.github/workflows/` 当前为空 → 无 CI。
- **为什么是低风险切片**：纯原生 GitHub Actions（复用，不建平台）；仅新增一个 YAML；直接强化闭环的"确定性验证"自动化闸门；PR 友好、可逆。
- **落地内容**：新建 `.github/workflows/ci.yml`，`on: [push, pull_request]`，job 含 checkout → setup-python 3.11 → `pip install pyyaml pytest`（按 `pyproject.toml` 补齐依赖）→ 运行 `PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -q`。
- **验收（AC）**：
  - [ ] `.github/workflows/ci.yml` 存在且为合法 YAML。
  - [ ] 工作流在 push/PR 触发，步骤含"安装依赖 + 跑引擎测试"。
  - [ ] 本地复跑 `PYTHONPATH=src python -m pytest src/ticket_autopilot/engine/tests/ -q` 仍 **7 passed**（无 regression）。
- **确定性验证**：`python -c "import yaml;yaml.safe_load(open('.github/workflows/ci.yml'))"`（合法 YAML）+ 引擎测试命令绿。
- **为何契合闭环**：把"确定性验证"从人工命令变成自动闸门，正是本票要证明的复用优先价值。

### 备选 A（文档类，若人类偏好零代码）
- 在某个 `research/` 或 `docs/` 文档中补一段"能力审计 → 闭环映射"的索引/交叉链接（指向 AIO-1 审计交付物）。须先确认 AIO-1 交付物路径存在，避免引用悬空。
- 验收：索引段落存在、链接可解析、markdown 合法。

### 备选 B（若人类另有指定）
- 人类把 AIO-5 置 In Progress 时可指定任意满足 §4 标准的工单。执行人类指定的；其余阶段不变。

> **执行规则**：若人类置 In Progress 时未指定候选 → 执行★推荐候选。若指定 → 执行指定项（仍须满足 §4）。

## 6. 六阶段执行 Runbook（每阶段开头先写 `[Goal check]` 行）
### 阶段 1 — 实现（Development）
- 用 Plane MCP 读取候选工单全文（若是★推荐候选，确认其对应 Plane 工单或新建一个 agent-ready 子任务）。
- 落地变更（如新建 `.github/workflows/ci.yml`）。**本地改动，不 push。**
- `[Goal check]` 示例：`[Goal check] 本阶段推进闭环 "Development"，证据 = .github/workflows/ci.yml 已写入工作区且 YAML 合法。`

### 阶段 2 — 确定性验证（Deterministic Verification）
- 运行验证命令（YAML 合法性 + 引擎测试）。全绿=通过；否则进入阶段 4 修复循环。
- 把命令 + 输出（绿）写入 goal-drift。

### 阶段 3 — 独立 QA（Independent QA）
- 因 AIO-7 Codex 连接器未建，用以下之一做独立复核：① Engine `verify` 节点（driver: llm 或 hermes）产 verdict；② 另一 agent/人独立核对 AC。
- 产出 `qa-verdict.json` 风格结论（对齐规范 §9：`decision=accept|reject` + 证据），写入 goal-drift。**仅 verdict，不修问题**（修问题走阶段 4）。

### 阶段 4 — 有界修复循环（Bounded Fix Loop）
- 若阶段 2/3 失败，回到阶段 1/2 修复，最多 **3 轮**（agent budget=3）；超次 → `BLOCKED_NEEDS_HUMAN`，记录并停。
- 每轮在 goal-drift 记一段（问题→修复→复验）。

### 阶段 5 — PR（Pull Request）— 人工门禁
- 准备：本地 commit（feature branch，如 `slice/aio5-ci`）。**不 push、不自动建 PR**，停下等人类审批（对齐 Human touchpoint Gate + 用户 git 写操作需显式批准）。
- 人类批准后：由人类或本 agent 在授权下 `gh pr create --fill --draft`（draft 即可，等人工 review/merge），PR 描述填 PR 模板、关联候选工单。
- 把 PR 链接写入 goal-drift。

### 阶段 6 — 工单状态更新（Status Update）
- PR 就绪后，用 Plane MCP 把候选工单（及 AIO-5 本身）状态推进（如 → In Review）；记录状态变更 + 时间戳到 goal-drift。
- AIO-5 自身：闭环证据齐全后，由人类置 Done（或本 agent 在授权下更新）。

## 7. 证据格式（`logs/goal-drift.md` Entry template）
每次阶段记录用如下结构（节选自现有模板）：
```
### YYYY-MM-DD — AIO-5 垂直切片：<阶段名>
**Status:** Corrected / Detected
### Intended outcome
<本阶段要推进的闭环阶段 + 可测证据>
### Observed divergence
<实际做了什么 / 产出了什么>
### Evidence
<仓库路径、命令、输出、时间戳、PR/issue 链接>
### Facts versus inference
**Facts:** ...
**Inferences:** ...
### Impact
### Correction or explicit reprioritization
### Guard added
### Recovery milestone
```
**每段工作开头必须有 `[Goal check]` 行**（AGENTS.md 强制）。

## 8. Definition of Done
- [ ] 选定 1 个真实低风险工单（满足 §4 标准）
- [ ] 6 阶段全部执行，每阶段在 goal-drift 有 Entry 证据（含 `[Goal check]`）
- [ ] 确定性验证命令全绿
- [ ] 独立 QA 产出 verdict（accept）并记录
- [ ] PR 已建（draft 即可）或人工门禁下 diff 就绪 + 决策已记录
- [ ] 工单状态已更新且链接 PR
- [ ] 暴露的胶水缺口已写入 goal-drift（指向 AIO-6/7/8/9），未越界实现

## 9. Risk & rollback
- 风险：误把 AIO-6/7/8/9 范围带进本票 → 回滚 = 删除越界代码，回到纯复用执行。
- 风险：PR 误 push main → 护栏 = feature branch + 人工 gate，绝不 push main。
- 回滚：git revert / 删分支即可；文档/YAML 类改动零风险。

## 10. Human touchpoints
- **Trigger**：人类把 AIO-5 置 In Progress（唯一启动动作）。
- **Gate**：人类 review 并 merge PR（PR 建 draft，不自动 merge）。
- **Escalation**：3 轮修复失败 → `BLOCKED_NEEDS_HUMAN`，带 goal-drift 证据上报。

## 11. 文件指针
- 闭环定义：`AGENTS.md`、`IDEA.md`
- 引擎：`src/ticket_autopilot/engine/engine.py`、`engine/cli.py`（run --mock）、`engine/tests/test_engine.py`
- 工单模板：`specs/agent-ready-ticket-template.md`（Worked example 参考）
- 证据模板：`logs/goal-drift.md`（Entry template）
- 候选落点：`pyproject.toml`（CI 依赖来源）、`.github/workflows/`（新增 ci.yml）
- 相关票：AIO-1 能力审计、AIO-2 闭环定义、AIO-6/7/8/9（本票缺口归它们）

## 12. 复用优先硬约束（最高优先级）
- 不新建平台/框架/引擎功能。
- 只用已存在能力：Plane MCP、`gh` CLI、Engine --mock、llm/hermes、goal-drift 模板、GitHub Actions。
- 任何"好像少个连接器"的冲动 → 记为缺口写入 goal-drift，交给对应 AIO 票，**不要顺手实现**。

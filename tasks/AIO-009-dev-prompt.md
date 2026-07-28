# AIO-9 开发提示词（Developer Prompt）

> 由 PM agent 生成，交给**开发 agent** 执行。开发 agent 开始前必须先读 `AGENTS.md` 与 `IDEA.md`，并在工作开头输出一行 `[Goal check]`。
> 这是一份 agent-ready 工单：置 In Progress 即可自主执行，无需中途人工决策。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane workspace `hspace`，project id `d40168f5-5d44-4810-a39e-3b6558e9bf6e`）
- 工单：AIO-9「实现 Engine 安全护栏（CLI 沙箱 + 只读 + 白名单）」
- Plane issue id：`00a8fb04-240d-4e3e-b15e-0a1a4fbbc3ce`（sequence_id 9）
- 优先级：high｜风险等级：**R1**（小而隔离、可逆的代码改动）
- ⚠️ 位置说明：AIO 任务在 **Plane**，不在 Linear（Linear 无 AIO 项目）。本提示词即任务说明来源。

## [Goal check]
本工作推进「开发（Development）」阶段，证据 = Engine 层三道护栏（目录沙箱 / 只读强制 / 工具白名单）落地 + `tests/test_guardrails.py` 全绿 + 既有 executor 路径无回归。

## 背景与项目现状（先对齐，避免重复造轮子 / 跑偏）
仓库**当前已具备**：
- **真实架构是 Engine 架构**：YAML 驱动的 DAG 解释器 `src/ticket_autopilot/engine/engine.py` + 4 类执行器 `src/ticket_autopilot/engine/drivers.py`（llm / cli / hermes / script）+ 语义重试闭环（verify 驳回 → 回 execute，最多 `vars.max_retries=5`）。
- `engine/drivers.py` **已有护栏雏形**（请勿从零重写，做扎实化 / 可配置化 / 可测试化）：
  - `DEFAULT_ALLOWED_ROOTS = ["sandbox"]`
  - `_resolve_within_root(relpath, engine_root, allowed_roots)`：校验 `cwd` 落在 allowed roots 内，否则抛 `SecurityError`。
  - `cli_call(...)`：已把 `--permission-mode read-only`、`--cwd`、`--allowedTools`（取 `agent.tools`）传给外部 CLI。
- 现有 workflow `src/ticket_autopilot/workflows/ticket-pipeline.yaml` 的 `executor` agent 用 `cwd: ./sandbox`、`permission_mode: read-only`、`tools: [Read, Glob, Grep]`。

**当前缺口（即本任务要补的）：**
- ❌ 目录沙箱只在 spawn 时检查一次，没有可复用的策略对象，也没有单测。
- ❌ **只读不是 Engine 层强制的**：若某节点 agent 把 `permission_mode` 设成 `write`，Engine 会照传——没有拦截。验收要求「写命令被拦截」，必须由 Engine 层保证，不能只依赖外部 CLI 自觉。
- ❌ **白名单未校验**：`cli_call` 把 `agent.tools` 原样传给 `--allowedTools`；若某 agent 写了 `tools: [Edit, Write]`，Engine 不会拒绝。验收要求「白名单外工具被拒」，需 Engine 层做 `节点 tools ⊆ 全局白名单` 的校验。
- ❌ 没有 `tests/test_guardrails.py`（当前 `tests/` 仅有 `__init__.py`）。
- ⚠️ 配置项（roots / read_only / whitelist）分散在常量和 agent 配置里，不可统一调（风险注记：白名单需可调，避免误拦合法命令）。

## 目标（Goal）
让 Engine 在 CLI 执行前，于**确定性的 Engine 层**强制三道护栏：目录沙箱、只读开关、工具白名单，防止 agent 越权；且这些护栏可配置（白名单 / roots 可调，避免误拦合法命令）。

## 范围边界
**In scope（交付物）：**
1. 抽出可复用的护栏策略模块（建议 `src/ticket_autopilot/engine/guardrails.py`），含 `GuardrailPolicy`（dataclass / config）：`allowed_roots: list[str]`、`read_only: bool`、`tool_whitelist: list[str]`（或 `disallowed_tools`）。
2. 目录沙箱：任何 CLI 节点的 `cwd` 必须在 `allowed_roots` 内，否则抛 `SecurityError`（复用并加固 `_resolve_within_root`）。
3. 只读强制：当 `read_only=True` 时，若节点 agent 请求的 `permission_mode` 非 `read-only`（或显式 `write`），Engine 直接拒绝（抛 `SecurityError`），不把写权限传给外部 CLI。
4. 白名单校验：节点 agent 请求的 `tools` 必须是 `tool_whitelist` 的子集；出现白名单外工具即抛 `SecurityError`。
5. 配置项：roots / read_only / whitelist 可配置（建议通过 workflow `vars` 或新增 `guardrails` 段 + 环境变量兜底），默认保持当前严格行为（roots=["sandbox"]、read_only=True；白名单默认取既有 `Read/Glob/Grep` 或「仅放行显式声明的」）。
6. 测试：`tests/test_guardrails.py`，覆盖越权路径、写模式、白名单外工具等用例。

**Out of scope（禁止）：**
- 网络隔离、沙箱虚拟化（容器 / nsjail）。
- 任何数据库迁移、生产访问、改 Plane/Linear 之外的系统。

## 验收标准（Acceptance Criteria）
- **AC-1 越权路径被拦截**：节点 `cwd` 落在 allowed roots 之外 → Engine 抛 `SecurityError` 且不 spawn CLI。
- **AC-2 写命令被拦截**：节点请求 `permission_mode: write`（或等价写权限）而策略 `read_only=True` → Engine 抛 `SecurityError`，不把写权限透传给外部 CLI（**不依赖外部 CLI 自觉**）。
- **AC-3 白名单外工具被拒**：节点 `tools` 含白名单外工具 → Engine 抛 `SecurityError`。
- **AC-4 配置项可调**：roots / read_only / whitelist 由配置驱动（非硬编码），且有测试演示「放宽白名单后原本被拒的工具被放行」。
- **AC-5 回归**：既有 `executor`（read-only + `[Read,Glob,Grep]` + sandbox）路径不被破坏——`engine/drivers.py` 仍可导入、既有 workflow 仍能加载、`tests/` 全绿。

## 验证方式（Verification — 确定性闸）
- 类型：**automated**（pytest）
- 命令：
  ```bash
  pytest tests/test_guardrails.py      # 必须全绿，含越权路径用例
  pytest                              # 仓库整体无回归
  python -m ticket_autopilot.engine run --mock   # 确认既有 headless 自测仍通过
  ```
- 通过 = AC-1 ~ AC-5 全部满足，`pytest` 全绿。失败 = 任一条 AC 不满足 → 进入有界修复（最多 2 轮）。

## 依赖（Dependencies）
- 名义依赖 AIO-2「定义并接通闭环工单工作流」。实际 Engine 核心（`engine.py` + `drivers.py`）已存在，本任务直接在 `drivers.py` 上加固，不阻塞于 AIO-2 完成；若发现缺 AIO-2 的接口，先按现状最小接入，超出部分记录到 PR 说明。

## 完成定义（Definition of Done）
- [ ] 护栏策略模块落地（`engine/guardrails.py` + `GuardrailPolicy`），被 `cli_call` 调用
- [ ] AC-1 ~ AC-4 均有对应单测且通过
- [ ] AC-5 回归验证通过（`pytest` 全绿、既有 workflow 可加载）
- [ ] 配置项存在且可调，默认保持严格行为
- [ ] 无新增 lint / 类型错误
- [ ] 产出 Developer Summary（人读，不参与状态判断）
- [ ] 由 Controller / 人工创建 PR（**开发 agent 不自行建 PR**）

## 风险与回滚（Risk & rollback）
- 风险：白名单过严会误拦合法命令 → 白名单必须可配置（见 AC-4），默认取既有最小集合。
- 回滚：纯代码 + 测试改动，`git revert` 即可；无数据 / 生产影响。

## 人工点位（Human touchpoints）
- **Trigger**：PM 将 AIO-9 置 In Progress（本提示词即启动信号）。
- **Gate**：PR 由人工 review 后合并（此改动动到执行器安全边界，必须人确认）。
- **Escalation**：若对「写命令」判定口径（是否要扫描 prompt 文本）有歧义，标记 `BLOCKED_NEEDS_HUMAN`，不要猜。

## 开发 agent 执行指引（步骤）
1. 读 `AGENTS.md`、`IDEA.md`、`engine/drivers.py`（现有 `_resolve_within_root`、`cli_call`）、`engine/engine.py`、`workflows/ticket-pipeline.yaml`。
2. 新建 `engine/guardrails.py`，定义 `GuardrailPolicy` 与 `check_cwd / check_permission_mode / check_tools` 三个纯函数（均抛 `SecurityError`）。
3. 改造 `cli_call`：在 spawn 前依次调用上述检查；`allowed_roots / read_only / tool_whitelist` 从 `agent` + workflow `vars`/配置解析，缺失时回退到当前严格默认值。
4. 写 `tests/test_guardrails.py`：覆盖 AC-1~AC-4（含「放宽白名单后被拒变放行」的正向演示）与 AC-5 的最小冒烟。
5. 本地跑 `pytest` 与 `python -m ticket_autopilot.engine run --mock`，确认全绿、无 import 回归。
6. Commit（message 含 `AIO-9`），输出 Developer Summary，**不要自行建 PR**。

## 硬性约束（来自 AGENTS.md）
- 复用优先、不新建平台：本任务本质是加固已有 `cli_call` 护栏，禁止引入新框架。
- 证据优先：不以「我觉得安全了」自证，以抛错 / 测试 exit 0 为证。
- 不扩大 Scope：只做 In scope 三项护栏 + 测试；网络隔离 / 虚拟化 / 迁移 / 生产一律 Out。
- 凭证从环境变量读取，不得写入任何配置文件。
- 不推 main、不 merge、不改 Plane/Linear 之外的系统、不碰生产密钥。

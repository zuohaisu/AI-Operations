# Dagu PoC — 对比结论：Dagu vs 我们的 orchestrator

> 日期：2026-07-27
> 背景：我们在做「工单驱动的 multi-agent 自动化流水线」（Plane 工单 → Plan agent → Execute agent → Verify agent → 关闭工单），目标是「只管工单，执行/验收/关闭全自动」。本 PoC 用 Dagu 把同一套流水线写成 DAG，端到端实跑一张真实 Plane 测试票，对比我们自己写的 orchestrator（`tooling/ticket-pipeline/orchestrator.py`）。

---

## 1. PoC 实际跑出了什么

### 1.1 Mock 版（无审批、headless）— ✅ 成功跑通真实 Plane API
文件：`dagu-poc/ticket-pipeline.mock.dagu.yaml`

DAG 跑到 `Result: Succeeded`，每一步真实命中 Plane：
- `ensure_ticket`：创建测试票 `92f878f7-…`（state=todo）
- `plan` / `execute` / `verify`：写 `artifacts/{plan.md,result.md,verify.json}`（mock 内容，不调 LLM）
- `close`：经 `plane_client` 真实 `add_comment(...)` + `set_state(..., "done")`
- `cleanup`：真实 `delete_issue(...)` 删除测试票

**结论：Dagu 的 DAG 依赖编排 + 步骤产物（artifact）+ 外部集成（复用我们已有的 `plane_client`）完全可用，且对真实 Plane API 的写操作（评论、置状态、删票）都被正确执行。**

### 1.2 完整版（带原生审批门）— ✅ 审批门正确挂起
文件：`dagu-poc/ticket-pipeline.dagu.yaml`

DAG 在 `verify` 之后、`close` 之前有一个 `approval:` 步骤。实跑时：

```
├─verify (succeeded)
├─approve [waiting]   ← Dagu 原生 human-in-loop 门生效，整条 DAG 暂停
├─close
└─cleanup
Result: Waiting
```

**结论：Dagu 原生支持「人在环」审批门，且能在 DAG 中途正确挂起等待人工放行。**

> ⚠️ **一个实测细节（重要）**：`dagu human-task complete ... --step approve` 报 `step "approve" is not a human task`。原因是 Dagu v2 的审批完成是**server-backed**（由 `dagu server` / web UI `:8080` 管理），而本地 `dagu start` 会正确挂起审批门，但 CLI 的完成指令需要服务端上下文。也就是说：**审批门能力是原生且可用的，但「程序化放行」依赖 Dagu 服务端（web UI 是主入口）**，比我们 orchestrator 在单进程内 inline 审批要重。

---

## 2. 逐项能力对比

| 能力 | 我们的 orchestrator（Python） | Dagu（2.11.0，单二进制） | 谁赢 |
|---|---|---|---|
| DAG 依赖 / 顺序编排 | 手写线性流程（plan→exec→verify→close） | YAML 声明式 DAG，原生 `depends` | **Dagu**（声明式、可并发、可嵌套） |
| 步骤间产物传递 | 进程内 dict（`result["plan"]` 等） | 原生 `stdout: { artifact: ... }` + 运行沙箱 | **Dagu**（有产物落盘、可审计） |
| **verify 驳回 → 重跑 execute 的循环** | orchestrator 内 ~30 行自己实现（while + 决策分支） | **原生不支持**；需靠「步骤失败重试」或外挂脚本模拟 | **orchestrator**（这里是我们的核心差异点） |
| **工单触发（适配层，非引擎能力）** | 当前内嵌 Plane 轮询（REST 直连），但本质是一层「工单源适配」 | 同样靠外部触发：webhook / scheduler / 别进程调 `dagu start` | **平手** —— 触发由「持有工单的系统」提供，不是引擎的护城河。换成 Multica（本身就是工单工具）就由 Multica 原生触发，引擎无需感知 Plane。 |
| 人工审批门 | inline 一行 `input()` / 自动通过（单进程） | **原生 `approval:` 门 + web UI 审批 + 审计** | **Dagu**（这才是它的强项） |
| 可观测性 / 审计 | 结构化日志（自写） | 运行历史、每步日志、web UI 仪表盘、状态机 | **Dagu**（开箱即用的可观测性） |
| 密钥管理 | `.env` 自己读 | 原生 secret + 输出脱敏 | **Dagu** |
| 运维成本 | 纯 Python 脚本，零外部依赖，无需常驻服务 | 单二进制、零外部 DB；但**要用人审/UI 就得起 server** | 平手（看是否要 UI） |
| 与外部 agent CLI 对接（claude / 各家 LLM） | 直接用 `subprocess` 调 `claude` CLI（走 Anthropic 兼容端点） | 同样用 `run: claude ...`，无差别 | 平手 |

---

## 3. 关键判断：真正「开源解决不了」的只有一块

⚠️ **修正（2026-07-27，Haisu 指出）**：此前把「Plane 工单触发」列为第二块硬骨头是**范畴错误**。触发不是引擎能力，而是「工单源适配层」——因为我们的工单现在恰好住在 Plane，才需要触发来认 Plane；换任何一个工单系统（Multica / Linear / GitHub Issues）都由该系统自己提供触发（轮询、webhook、或原生 issue 触发），引擎层面两者对称：Dagu 不认 Plane，我们的 orchestrator 也只是内嵌了一层 Plane 轮询，并非引擎的护城河。

所以真正「开源一个都没覆盖」的只有一块：

1. **verify 驳回 → 回到 execute 的循环**：这是「agent 自控闭环」的本质。Dagu 是「跑完即止」的调度器，没有「根据某步输出决定回退到上游重跑」的原生语义（它的 retry 是「步骤失败重试」，不是「根据语义决策回退」）。我们的 orchestrator / VFF 这 30 行正是价值所在。
2. ~~Plane 工单触发~~ → 降级为「工单源适配层」（见 §2 该行）：引擎只消费一个 `ticket_id`，触发由持有工单的系统提供。VFF 当前把 Plane 绑定局部化在 `close_ticket` handler + 一个未来的 trigger 适配，引擎本身与工单系统无关。

换句话说：**引擎层 Dagu 比我们写得好，且「触发」对它并非短板（那是工单系统的事）；唯独「控制闭环」这块薄逻辑 Dagu 接管不了，还是得我们自己写。** 用 Dagu 只需在「Dagu 编排」与「我们的闭环步骤」之间缝一层，触发本身不用搬。

---

## 4. 结论与建议

### 建议：**保留我们的薄 orchestrator 作为 agent-native 控制层；Dagu 暂不替换它。**

理由：
- 当前只有「一条流水线、一人用」的场景，orchestrator 的 ~200 行已经把触发 + 闭环 + 关闭全包了，零常驻服务、零额外运维。
- 换成 Dagu 并不能删掉我们的核心逻辑（**闭环**——触发是工单系统的事，不是核心），只是把「DAG 编排」从手写变声明式——收益有限，却要引入 server（若要用审批/UI）、webhook 对接等额外面。
- Dagu 真正的优势（web UI、审计、secret、多工作流调度、声明式 DAG）在我们「规模上来、要多人/多流水线/要可视化审批」时才划算。

### 什么时候该上 Dagu（或同类）：
- 流水线从 1 条变 N 条，需要统一调度、可视化、运行历史与审计；
- 需要非技术角色在 web UI 上做审批（这正是 Dagu `approval:` 的强项）；
- 需要 secret 管理与输出脱敏的开箱能力。
届时架构应为：**Dagu 做「调度 + UI + 审批 + 审计」外壳，我们的 orchestrator 退化为「被 Dagu 调用的一个 agent 闭环步骤」**（即 Dagu 管编排与人审，内部那步仍跑我们的 verify→execute 循环）。这是干净的分工，而非二选一。

### PoC 已验证、可复用的资产
- `dagu-poc/ticket-pipeline.mock.dagu.yaml` — headless 端到端（真实 Plane 写操作）
- `dagu-poc/ticket-pipeline.dagu.yaml` — 含原生审批门的完整形态
- `dagu-poc/{ensure_ticket,plan,execute,verify,close,cleanup}.py` — 六个步骤脚本，复用 `../plane_client.py`
- 跑法：`dagu start <绝对路径>/ticket-pipeline.mock.dagu.yaml`（绝对路径；Dagu 按名解析到 `~/.config/dagu/dags/`，相对名会找不到）
- 踩坑已记录：v2 所有 key 必须 snake_case（`workingDir`→`working_dir`）；审批步骤需带 `run`；程序化放行需 `dagu server`。

---

## 5. 最终一句话
**Dagu 证明了「通用引擎」这层开源已经解决；我们这条流水线的护城河其实只有一块——verify 闭环（「Plane 触发」是工单源适配层，引擎无关，换 Multica 就由它原生触发）。所以先不换引擎，保持薄 orchestrator/VFF；等规模/可视化/人审需求上来，再把 Dagu 当外壳包上来。**

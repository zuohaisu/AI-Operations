立即执行：你是本 Run 的 Developer Agent，在无需追问的情况下立刻开始执行下述任务，完成后停止。

# Ticket
- Issue key: **AIO-21** — 用本地 Web 控制台完成首个 Personal Phase 1 Pilot
- Repository path: `/Users/hzuo/Documents/code/AI-Operations` (zuohaisu/AI-Operations)
- Risk Tier: R0（文档型改动）

# 角色边界（Developer role boundary）
你只承担 Developer 角色：实现改动并自证，不得同时扮演 QA、不得给自己出具 verdict、不得代替 Controller 执行 Commit/Push/PR/Merge、不得修改或补造 events、verdict、manifest 等 Controller 所有的证据。QA 由独立的 Acceptance Agent 执行。

# 任务（唯一允许的改动）
只更新仓库根目录的 `README.md`，以下两处改动都必须完成：
1. 明确唯一启动入口是 `./start-ticket-autopilot`（等价于现有的 `python -m ticket_autopilot.web start`）：命令返回后服务在 `127.0.0.1:8765` 持续运行，随后通过浏览器继续操作；说明前置条件（Python 3.11+、Git、可用的 Planner/Developer/QA Agent CLI、本机 Plane 配置、干净的仓库基线）与实际操作流程（在页面选择 Ticket → 点击一次 `Run Ticket Autopilot`（缺 Prompt 时自动由 Planner 生成 dev/acceptance Prompt，人工复制次数为 0）→ Developer → deterministic checks → 独立 QA（最多 5 轮修复）→ PASS 后由 Controller 创建本地 Commit；Timeline、events、state 全过程可回读；终态只有 COMPLETED / HARD_BREAK / QA_EXHAUSTED，后两者不得报告为成功）。
2. 删除“当前已知可靠性问题”一节中关于 `service_id` 参数被命令行误解析导致本机健康检查超时的说明——该缺陷已通过 `--service-id=<value>` 单参数写法在服务端修复（`src/ticket_autopilot/web.py`），不得继续把已修复的问题记录为未解决。

# 硬性约束
- forbidden_paths：不得触碰 `src/**`、`tests/**`、`.github/**`、`specs/**`、`tasks/**`。
- max_changed_files: 1 —— 你的 diff 只能包含 `README.md`。
- 不 Push、不建 PR、不 Merge、不写 Plane 状态、不自行 Commit（Commit 由 Controller 的 Commit gate 在 QA PASS 后执行）。
- allow_main_push: false。

# Diff 归因与工作区纪律
- 每一处改动都必须可归因：完成时逐项列出 changed files 与每个 hunk 对应的 AC/任务条目（本票改动应归因到 AC-1/AC-2/AC-6 所述 README 说明与已修复缺陷说明的移除）。
- 除本任务 `README.md` 的未提交改动外，工作区必须干净（non-dirty）：不得留下临时文件、脚本、备份或任何未归因改动；执行前先用 `git status --porcelain` 确认基线干净，发现无法归因的脏文件立即停止并如实上报（HARD_BREAK 候选），不得掩盖或顺手提交。

# 验证（自证，不等于 QA verdict）
- 运行 Required Checks 并报告真实退出码：`python3 -m pytest -q`。
- 用 `git status --porcelain` 与 `git diff --stat` 证明改动仅 `README.md`。

# 条件式视觉证据门（visual）
本票为 README 文档改动，不涉及 UI/前端渲染改动时无需视觉证据；但如果你的改动以任何方式影响页面呈现（本票不应发生），必须提供页面截图等视觉证据并标记 `HUMAN_VISUAL_REVIEW_PENDING`，该状态是证据状态，不得报告为 PASS。

# 完成报告
报告：改动文件清单、逐 hunk 的 diff 归因、Required Checks 退出码、工作区干净性证明。任何需要越界（改产品代码、放松门禁、手工补证据）的情况一律停止并标记 HARD_BREAK，不得伪装成功。
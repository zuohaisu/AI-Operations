# AIO-3 验收提示词（Acceptance / QA Prompt）

> 由 PM agent 生成，交给**独立测试 / 验收 agent**。验收 agent 独立于开发 agent，只做验证与判定，**不修改任何文件**。

## 任务身份
- 项目：Ticket Autopilot / AIO（Plane）
- 工单：AIO-3「项目脚手架骨架」（issue `c76822b0-223d-4dd9-bf0c-a323097eab42`）
- 风险等级：R0｜类型：文档/脚手架 **inspection 验收**
- ⚠️ 位置说明：AIO 任务在 **Plane**，不在 Linear。

## [Goal check]
本工作推进「独立验收（QA）」阶段，证据 = 逐条核对 AIO-3 的 6 条 AC，产出 PASS/FAIL 判定 + 证据清单。

## 你的角色与权限
- 你是**独立验收 agent**，目标：判断 AIO-3 交付物是否满足验收标准。
- 你可以：读取仓库所有文件、运行**只读**检查命令（如 `test -f`、`grep`、链接检查）。
- 你**不可以**：修改代码/文档、Commit、Push、Merge、建 PR、改工单、改验收标准。
- 若文档不足或存在缺口，必须输出 **FAIL** 并列出具体缺口（不替开发 agent 补做）。

## 输入
- AIO-3 工单原文（见开发提示词或 Plane issue）
- 开发提示词中定义的 6 条 AC（AC-1 ~ AC-6）
- 待验收的 PR / 分支 diff

## 验收方法（证据优先）
逐条核对以下清单。每条必须给出**证据**（文件路径 + 具体满足的内容摘录），不得仅凭“看起来有”。

### AC-1 — CONTRIBUTING.md 内容齐备
- 证据：`CONTRIBUTING.md` 存在；且至少覆盖：分支命名约定、PR 模板使用、review/merge 人工闸、agent 建 PR 约定、闭环状态映射（In Progress / In Review / Blocked）。
- 判定：全覆盖 = PASS；缺任一项 = FAIL（列缺失项）。

### AC-2 — PR 模板结构齐备
- 证据：`.github/PULL_REQUEST_TEMPLATE.md` 存在；且含 关联工单、Goal、Scope(in/out)、AC 勾选清单、验证证据、风险/回滚 至少 6 区块。
- 判定：缺区块 = FAIL。

### AC-3 — memory 布局说明
- 证据：`.workbuddy/memory/README.md` 存在，说明 MEMORY.md（长期）与 `YYYY-MM-DD.md`（每日）的用途、写入时机、不写什么。
- 判定：三项都说清 = PASS，否则 FAIL。

### AC-4 — ticket 模板对齐 senior-PM 格式
- 证据：`specs/agent-ready-ticket-template.md` 标注对齐 9 字段，且含「空白可填模板」+「spec → Plane issue 操作流程」。
- 判定：两节都在 = PASS，否则 FAIL。

### AC-5 — README 自描述
- 证据：根 `README.md` 描述目录结构，并链接 `CONTRIBUTING.md` / PR 模板 / `.workbuddy/memory/README.md` / `specs/agent-ready-ticket-template.md`。
- 判定：结构描述 + 4 个链接都在 = PASS。

### AC-6 — 无失效内部链接
- 证据：上述所有新增/修改 `.md` 的交叉链接指向的本地路径真实存在（用 `ls`/读取验证）。
- 判定：无失效 = PASS；任一失效 = FAIL（列失效路径）。

## 附加检查（Scope 越界）
- 检查 diff 是否触碰 `src/` 产品代码、是否新建平台/服务/CLI。若越界 → FAIL（scope violation），并在 findings 标注。

## 验证命令（只读，可运行）
```bash
for f in CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md \
         .workbuddy/memory/README.md specs/agent-ready-ticket-template.md README.md; do
  test -f "$f" && echo "OK  $f" || echo "MISSING  $f"
done
```

## 产出（qa-verdict 风格）
输出一份结构化判定（无需严格 JSON Schema，但建议下列字段）：
```
verdict: PASS | FAIL | BLOCKED
issue_key: AIO-3
run_id: <本次验收标识>
acceptance_criteria:
  - id: AC-1 .. AC-6
    status: PASS/FAIL
    evidence: <文件路径 + 内容摘录>
findings:
  - id: QA-001
    severity: blocker|major|minor
    type: <MISSING_CONTENT | SCOPE_VIOLATION | BROKEN_LINK | INSUFFICIENT>
    summary: ...
    required_fix: ...
recommended_next_state: PASS | FIXING | BLOCKED_NEEDS_HUMAN
```
- 全部 AC PASS 且无 blocker/major → `verdict: PASS`。
- 任一 AC FAIL 或存在 blocker/major → `verdict: FAIL`，并要求开发 agent **只修 findings**。
- 对“senior-project-manager 格式”口径无法判定 → `verdict: BLOCKED`（BLOCKED_NEEDS_HUMAN）。

## 禁止事项
- 不修改任何文件（含文档与测试）。
- 不自行补做缺失文档。
- 不放松 AC 标准以通过。

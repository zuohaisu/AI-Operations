立即执行：作为独立只读 QA，审查票据 AIO-27 在仓库 `/Users/hzuo/Documents/code/AI-Operations` 中的拟议 diff 与 Controller 提供的确定性证据。

[Goal check] This work advances the Independent QA stage by independently evaluating the proposed AIO-27 diff and recorded deterministic evidence before the Controller commit.

你是独立 QA。保持严格的只读边界：不得编辑文件、暂存、提交、push、创建 PR、合并、更新票据、启动服务，或要求 Developer/Controller 作出范围外改动。QA 必须在 Controller 创建本地 commit 之前评估拟议 diff；QA PASS 不得以已有 commit 或干净 worktree 为条件。

审查合同：仅允许新建 `docs/manual-pilot-checklist.md`，且它必须是 AIO-27 唯一的 changed path。不得有 `src/**`、`tests/**`、`specs/**`、`tasks/**`、`.github/**` 或任何现有文档的改动。对每个实际变更提供 diff attribution：路径、与 AIO-27 AC-1/AC-2/AC-3 的关系，以及是否超出范围。记录当前 `git status --short` 和可读 diff；将非 AIO-27 改动、未归属改动或多路径改动报告为 FAIL/阻塞交付问题。

审阅 Controller-supplied deterministic command evidence（命令、退出码、原始输出、执行时的 diff/状态上下文），至少包括：三条 AC-1 至 AC-3 的 `python3 -c` 验证命令，以及 `python3 -m pytest -q` 的退出 0 证据。不得自行重跑 `pytest`，也不得运行任何会写入缓存、字节码或临时文件的命令；不得以重新执行写入型命令替代证据审阅。可仅使用不会改变仓库或运行时状态的只读检查。

验证内容：

- AC-1：`docs/manual-pilot-checklist.md` 存在，且 AIO-27 只有该路径变更。
- AC-2：文档包含 `## Before Run`、`## During Run`、`## After Run`，并准确说明启动服务、访问 `http://127.0.0.1:8765/`、选择 eligible ticket、单次点击 Run、Planner → Developer → deterministic checks → independent QA、`COMPLETED`、local commit、retained events 和 retained worktree。
- AC-3：`## Failure Handling` 分别说明 `BLOCKED`、`HARD_BREAK`、`QA_EXHAUSTED` 应检查的证据，且未把任何非成功终态称为 `PASS`。

visual：本票为 Markdown-only 变更，默认不需要视觉证据；若拟议 diff 实际涉及 UI、浏览器流程或视觉呈现，则视觉证据为必需项，缺失时不得 PASS，并应报告范围漂移。

工作树规则：记录并归属当前 dirty 状态；Controller 在其后续提交/交付阶段必须恢复干净（non-dirty）worktree，但该要求不是本次独立 QA PASS 的前置条件，也不能用于拒绝对未提交拟议 diff 的 QA 结论。

输出结论必须为 `PASS`、`PASS with comments` 或 `FAIL`，逐项映射 AC-1 至 AC-3、diff attribution、确定性证据审阅结果、视觉 gate 状态及风险。不得把 `BLOCKED`、`HARD_BREAK`、`QA_EXHAUSTED`、待验证或缺失证据重写为 PASS。
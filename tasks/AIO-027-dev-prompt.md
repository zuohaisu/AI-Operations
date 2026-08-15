立即执行：在票据 AIO-27 的仓库 `/Users/hzuo/Documents/code/AI-Operations` 中完成受限的文档变更。

[Goal check] This work advances the Development stage by producing one attributable checklist diff and deterministic evidence for AC-1 through AC-3.

你是 Developer。你的职责仅限于实现和自检；不得承担 Controller、独立 QA、提交、推送、PR、合并或票据状态更新职责。

范围：只新建 `docs/manual-pilot-checklist.md`，不得修改任何现有文件。禁止修改 `src/**`、`tests/**`、`specs/**`、`tasks/**`、`.github/**`，也不得改变产品行为、配置、生成 Prompt、远程访问或交付设置。总变更文件数必须为 1。

先以只读方式检查现有 Web 启动方式和 Run 的真实终态语义，避免文档臆测。清单必须包含 `## Before Run`、`## During Run`、`## After Run`、`## Failure Handling`，并准确覆盖：启动服务、打开 `http://127.0.0.1:8765/`、选择 eligible ticket、只点击一次 Run、观察 Planner → Developer → deterministic checks → independent QA、确认 `COMPLETED`、本地 commit、retained events 与 retained worktree。Failure Handling 必须分别说明应检查的 `BLOCKED`、`HARD_BREAK`、`QA_EXHAUSTED` 证据，且绝不可将非成功状态描述为 `PASS`。

为每一项变更提供 diff attribution：说明该路径为何属于 AIO-27、其对应的验收标准，以及确认没有其他路径被此任务改动。交接前检查 `git status --short` 和 diff；AIO-27 的交付完成后应由 Controller 提交并恢复为干净（non-dirty）worktree。不得擅自提交以伪造该状态。

执行并记录原样输出及退出码：

```sh
python3 -c "from pathlib import Path; p=Path('docs/manual-pilot-checklist.md'); assert p.is_file()"
python3 -c "from pathlib import Path; t=Path('docs/manual-pilot-checklist.md').read_text(); required=('## Before Run','## During Run','## After Run','Planner','Developer','deterministic checks','QA','COMPLETED','commit'); assert all(x in t for x in required)"
python3 -c "from pathlib import Path; t=Path('docs/manual-pilot-checklist.md').read_text(); required=('## Failure Handling','BLOCKED','HARD_BREAK','QA_EXHAUSTED','PASS'); assert all(x in t for x in required)"
python3 -m pytest -q
```

visual：本票仅新增 Markdown，默认不需要视觉证据；只有发现任务实际影响 UI、浏览器流程或视觉呈现时，才必须提供可复核的视觉证据，并将此范围扩张报告为阻塞或升级事项。

交接给 Controller：提供变更摘要、逐路径 diff attribution、`git diff --check` 与 `git status --short` 结果、全部确定性命令证据、任何风险或未验证事实。不要创建 commit、push、PR 或 merge。
# 研究：用一套方法对比不同的 Start Prompt 谁好谁坏

> 研究场景：深度研究本项目目录（AI-Operations）
> 日期：2026-07-22
> 对象：`core/` `modules/` `platform/` `eval/` 与 `00 Inbox/` 中的历史研究笔记

---

## 0. 一句话结论

这个项目本身就在"造一个通用的 Start Prompt（AI Agent 操作系统提示词）"，并且**已经自带了一套相当扎实的多模型对比实验 `eval/Benchmark-02`**。它已经能严谨地回答「v4 和 v5 谁更好」，但**还没有一套可复用、可对比「任意多个」Start Prompt 的通用方法**。

本文做两件事：
1. 说清楚这个项目在建设什么、现有 Benchmark-02 是怎么做对比的、强在哪、缺口在哪；
2. 给出一套**通用方法（SPCM — Start Prompt Comparison Method）**，把「v4 vs v5」这个一次性实验升级成「任意 N 个 Start Prompt 都能比」的可复用方法，并附上在现有 `eval/` 之上落地的改造清单。

---

## 1. 这个项目在建设什么

**目标**：一个「海粟通用 AI Agent 操作系统提示词」（Universal Start Prompt）。特点：
- 项目无关、工具无关，可整段贴进 Claude Code / Codex / WorkBuddy / Cursor / Qoder / Trae / Hermes 的 System/Start Prompt 字段；
- 角色是「海粟」本人（偏产品 / 系统 / 认知结构设计），定位是「认知合作者 + 执行杠杆 + 诚实的第二大脑」，不是 chatbot，不是编码小助手；
- 优化目标是「我长期决策的质量 + 产出的可复用性」，而非「这一条回复让我满意」（`eval/prompts/v5.md` 第 12–17 行）。

**模块化真源（source of truth）**：
- `core/`：8 个核心段 —— identity / startup / autonomy / failure / epistemics / language / routing / output
- `modules/`：6 个任务模块 —— decision / engineering / product / research / system / writing

**发布构建**：
- `v4`（`eval/prompts/v4.md`）：当前已发布单文件，约 215 行，结构 §0–§9；
- `v5`（`eval/prompts/v5.md`）：由 `build_v5.py` 把顶层 `core/` + `modules/` 拼成单文件，约 297 行，结构更紧凑、行为规则更硬（如「两次失败即停」是硬门、`INSPECTION IS FREE, A WRONG WRITE IS NOT`）。

**平台层 `platform/`**：按工具分发的 delta（`claude_code` / `codex` / `chat` / `tools`），处理「同样的 core 在不同工具上怎么存、autonomy 是真门还是建议」。

**关键事实（可复现性）**：`eval/prompts/v5_core/` 与 `v5_modules/` 是顶层 `core/`、`modules/` 的**逐字节副本**；`build_v5.py` 实际从顶层 `core/`、`modules/` 读取并重建 `v5.md`。也就是说**顶层 `core/`+`modules/` 才是真源**，`eval/prompts/v5_core` 只是 freeze 时的快照。改顶层源文件不会自动改 `v5.md`，必须先跑 `build_v5.py`。

---

## 2. 现有方法全景：Benchmark-02 怎么对比 Start Prompt

`eval/` 是一套**冻结式、可复现、多模型、双盲判分**的对比实验，核心文件：

| 文件 | 职责 |
|---|---|
| `config.yaml` | 模型、3 个 arm、profiles、解码参数、judge 配置 |
| `cases/cases.json` | 17 条用例（含 3 条 holdout），每条带正/负向与判分标准 |
| `run.py` | 生成阶段：发系统提示词 + 用户轮，产出 blinded 响应，绝不判分 |
| `judge.py` | 判分阶段：双盲（不知道模型/arm/版本）、LLM 多数投票 |
| `report.py` | 按模型/类别汇总，Wilson 95% 区间，给出胜负裁决 |
| `freeze.py` | 锁定 config/cases/prompts/contract/runner/模型指纹 |
| `build_v5.py` | 从模块化源重建单文件 v5 |
| `benchmark_lib.py` | 哈希、校验、artifact 复制等共享工具 |
| `model_client.py` | OpenAI / Anthropic 两种 transport 适配器 |

**实验设计要点**：
- 三个 arm：**A=bare（无提示词）**、**B=v4**、**C=v5-single**。`bare` 是强制基线，用来区分「是提示词贡献的」还是「基座模型本来就有的能力」（`SCORING_CONTRACT.md` §2）。
- 主估计量：每个模型**内部**的 `V5 pass rate − V4 pass rate`，而不是跨模型排行榜（`SCORING_CONTRACT.md` §1）。
- 4 个目标模型（GLM 4.7 / DeepSeek V4 Flash / gpt-oss-120b / Nemotron 3 Ultra），解码参数在 arm 间完全一致。
- 判分类型：`regex` / `prog` / `schema`（确定性）+ `llm`（双盲多数投票）。
- 正/负向用例成对：正向测「该触发的行为触发了没」，负向测「过度触发没有」；过度触发率作为 `1 − pass rate` 单独报（`SCORING_CONTRACT.md` §5）。
- 硬失败（hard fail）单独追踪、绝不平均掉（如：未授权删除、同一症状第三次猜测、编造市场数据）。
- 统计纪律：Wilson 95% 区间；**只有当下界 > 对方上界才算赢**，否则 `inconclusive`；硬失败回退优先于区间裁决（`SCORING_CONTRACT.md` §8）。
- 防过拟合：`pilot`（校准）→ `development`（5 run/格）→ `holdout`（仅 holdout 用例，独立跑、独立报）。
- 裁判校准 + 人工审计：裁判模型不在 4 个目标模型里；人工标注 30–50 条校准到 <5% 误差；采纳前必须人工读每一条 hard fail、0%/100% 标准、非 inconclusive 裁决、≥10 条随机 PASS。
- 冻结与可复现：API key 不进 freeze；端点只存 SHA-256 指纹；run/artifact 哈希全程校验，runner 漂移直接报错。

---

## 3. 现有方法的优点（强在哪）

1. **真冻结、真可复现**：config/cases/prompts/judge/runner/模型指纹全锁定 + 哈希校验，是工程级严谨度，远好于「改完 prompt 再跑一次看感觉」。
2. **双盲判分**：judge 不知道模型、arm、版本，避免「v5 更新所以更高分」的偏见。
3. **硬失败不平均**：安全/不可逆行为回退单独标记，避免被总通过率掩盖。
4. **正/负向成对**：既测「该做的做了没」，也测「不该做的没做」，防止「更激进 = 更好」的误判。
5. **统计纪律清楚**：Wilson 区间 + 非重叠才判赢 + 硬失败优先，结论保守可信。
6. **holdout 防作弊**：开发集上看到的结论不能用 holdout 反推改 prompt。
7. **成本单列**：token / 延迟与「行为质量」分开报，不混为一谈。
8. **有测试套件**：`tests/test_benchmark.py` 覆盖了 config 校验、矩阵规模、正/负向覆盖、报告裁决、judge 缓存、transport 适配。

---

## 4. 现有方法的局限（相对「对比任意 Start Prompt 谁好谁坏」的目标）

| # | 局限 | 影响 |
|---|---|---|
| 1 | **被 v4/v5 写死**：`validate_config` 强制 `conditions == ["A","B","C"]` 且 A 必无 prompt（`benchmark_lib.py` 第 122–126 行）。对比任意 N 个候选必须改 schema、改代码。 | 无法「随手丢两个新 prompt 进来比」。 |
| 2 | **单一裁判模型，无 ensemble**：judge 偏见是未控制的混杂变量。 | 裁判模型自身偏好可能系统性偏向某类 prompt 文风。 |
| 3 | **开放文本质量明确 out of scope**：文笔、洞察深度、长研究报告质量被 `SCORING_CONTRACT.md` §4 排除。 | 「谁更好」常常恰恰卡在文笔/洞察，现有方法测不到。 |
| 4 | **纯文本、无工具执行**：autonomy/failure/safety 只测「声称行为」，无真实工具调用验证。 | 这些维度的结论是「 provisional」的，不能当真采纳。 |
| 5 | **用例库窄（17 条）**：覆盖 8 类够做回归，但不足以度量广度质量。 | 新 prompt 在某类任务上的长尾问题可能测不到。 |
| 6 | **质量维度与代码耦合**：`category` 来自 `cases.json`，没有一份「独立于任何 prompt 的质量维度清单」。 | 比 prompt 时维度随用例走，难以横向对齐。 |
| 7 | **缺少「用比较法改进 prompt」的开发回路**：contract 禁止看结果后改 prompt（对裁决正确），但没有一个**隔离的**开发环让人「比 → 改 → 再比」。 | 只能做一次性裁决，不能把比较法当成迭代工具。 |
| 8 | **跨模型可移植混杂**：结论是 per-model，没有明确的跨模型聚合规则（哪些算「胜利」）。 | 「v5 在 3/4 模型更好」这种结论靠人读，没固化。 |
| 9 | **成本-质量 Pareto 缺失**：prompt 长度（占上下文）是重要维度，但只在 report 里当 usage 顺带报。 | 「更长但更好」是否值得，没有纳入「更好」的判据。 |

---

## 5. 提出的通用方法：Start Prompt 比较方法（SPCM）

把上面的强项保留、缺口补齐，得到一套 9 层的通用方法。**核心思想：把「比什么维度、用什么用例、怎么判分、怎么裁决」与「具体哪几个 prompt」彻底解耦。**

```
Layer 0  定义问题        arms（≥2 候选 + ≥1 基线: bare 或现网版）、目标模型（≥1，建议 2–4）、
                        决策估计量（模型内 pairwise Δpass，非排行榜）
        │
Layer 1  质量维度清单    独立于任何 prompt 的固定维度：自主门控 / 失败克制 / 认知诚实 /
        （taxonomy）     决策结构 / 范围控制 / 语言纪律 / 启动定向 / 输出完整度
                        + 独立的「定性轨道」（文笔/洞察/研究深度）
        │
Layer 2  用例库          分层：每条 = 维度 + 极性(正向应触发/负向不应过度触发) + tier + 附件?
        （case bank）    + hard_fail 标记 + 判分标准。≥30 条，含 holdout 盲集。
        │
Layer 3  生成（双盲）    对每个 (模型 × arm × 用例 × run) 发 system+user，存文本+usage+latency；
                        顺序打乱、响应哈希、配置变了绝不复用
        │
Layer 4  判分            确定性(regex/prog/schema) + 双盲 LLM 多数投票；
                        judge 模型盲、标准盲；≥2 judge 或 1 judge+人工抽检；报 self-agreement，
                        低于阈值=该标准不可靠；hard fail 单列；负向用例过度触发率单列
        │
Layer 5  聚合与裁决      每(模型×维度×arm)：通过率 + Wilson 95% 区间；
                        pairwise：下界>对方上界才算赢，否则 inconclusive；
                        hard-fail 回退优先；token/延迟单列（成本-质量前沿）；不用单一综合分当唯一依据
        │
Layer 6  定性轨道        对开放文本（写作/研究/决策洞察）跑独立 rubric（1–5：相关/结构/洞察/诚实/可复制），
                        由人或强 judge 评。补 Layer 4 测不到的半边
        │
Layer 7  Agentic 验证    对 autonomy/failure/safety，在 sandbox agent 里跑真工具，验证实际调用
        （可选但推荐）    是否匹配声称的门控。Layer 3 的文本结论在通过此层前为 provisional
        │
Layer 8  治理/可复现      freeze(config+prompts+cases+judge+runner)、哈希校验、judge 校准(<5% 误差)、
                        强制人工审计、development 与 holdout 分离、holdout 绝不反推改 prompt
        │
Layer 9  迭代回路        隔离的「开发环」：pilot→读失败→改 prompt→再 pilot（不需 freeze、允许改）。
        （用于「做出更好   只有最终候选进 Layer 8 的冻结裁决门。把比较法当成迭代工具，而非一次性裁判
        的 prompt」）
```

### 5 个关键设计决策

1. **arms 解耦**：`config` 不再写死 A/B/C，改成 `arms: [{id, label, prompt_path, role: baseline|current|candidate}]`，支持 N 个候选、任意标签、任意指定基线。
2. **维度先行**：先定一份 `dimensions.yaml`（维度 + 每条的正/负向探针），用例只引用维度 id。这样「比什么」不再随用例散落。
3. **双轨判分**：行为类用现有 `judge.py`（确定性 + 双盲 LLM）；开放文本类新增 `qual.py`（rubric 评分）。两轨结论分开、最后合并。
4. **成本进判据**：把「prompt 长度 / 每轮 token」纳入采纳门，给出「质量-成本前沿」，让「更长更好但更贵」可权衡。
5. **开发环与裁决门分离**：新增 `profile: dev-loop`（不冻结、允许改 prompt、只看方向），避免为了迭代破坏冻结实验的严谨性。

---

## 6. 怎么在现有 `eval/` 之上落地（改造清单）

按性价比排序，最小改动即可把「v4 vs v5」升级成「任意 N prompt 对比」：

1. **泛化 arms（解 #1）**：改 `benchmark_lib.validate_config`，允许 `conditions` 长度为 ≥2，去掉「A 必无 prompt」硬约束，改为在 `scoring` 里用 `baseline/current/candidate` 角色字段指定对照关系（`config.yaml` 已有 `scoring` 段可用）。
2. **多 judge 集成（解 #2）**：`config.yaml` 的 `judge` 改为 `judges: [...]` 列表；`judge.py` 对每个 `llm` 标准跑多 judge，报 per-judge 一致率；任一 judge 与多数不一致时标记待人工复核。
3. **新增定性轨道（解 #3）**：加 `qual.py` + `qual_cases.json`（开放文本用例 + 1–5 rubric），输出 `qual_scores.json`，`report.py` 增加「定性轨道」一节。
4. **加 agentic 验证桩（解 #4）**：新增 `agentic.py`，在 sandbox 里用真实文件/Shell 跑 T03/T04/T17，断言实际工具调用，产出 `agentic_report`。Layer 3 文本结论标注「待 agentic 验证」。
5. **扩用例库（解 #5/#6）**：新增 `dimensions.yaml` 作为维度真源；把 `cases.json` 扩到 ≥30 条并按维度分层；保留 holdout。
6. **加 dev-loop profile（解 #7）**：`config.yaml` 增 `dev-loop`（不需 freeze、允许改 prompt、1 run/格、仅做方向指示），让「比→改→再比」可操作。
7. **跨模型聚合规则（解 #8）**：在 `report.py` 加 `adoption_gate()` 函数，固化「≥多数模型非劣/更优 + 改进跨模型复现 + 无新 hard fail」的判定（逻辑已在 `SCORING_CONTRACT.md` §12，只是没代码化）。
8. **成本进判据（解 #9）**：`report.py` 在总表加「prompt 长度 / 平均输入 token」列，给出质量-成本前沿说明。

---

## 7. 怎么裁决「谁更好」（adoption gate）

综合现有 `SCORING_CONTRACT.md` §12 与本文补齐项，一条候选 prompt 被判定为「更好」需**同时满足**：

- ① 在任意目标模型上**无新增 hard fail**；
- ② 在**过半模型**上统计非劣或更优（Wilson 区间非重叠才计赢）；
- ③ 任何声称的类别改进在**≥3 个模型**上复现；
- ④ 过度触发（负向用例误触发）可控或明确可接受；
- ⑤ 定性轨道（文笔/洞察/研究）**不劣于**基线；
- ⑥ 在**可接受的 token 预算**内（prompt 长度占上下文比例合理，质量-成本前沿上不显著失衡）；
- ⑦ judge 校准误差 <5%，且强制人工审计完成；
- ⑧ 文本-only 的行为类结论，若影响采纳，须标注「待 agentic 验证」。

未全部满足时，正确结论一律是 `not yet established`，而不是 `X wins`。

---

## 8. 下周可执行的 3 件事

1. **先把 arms 泛化**（改造清单第 1 条）：半天内可把「v4 vs v5」变成「丢任意 prompt 进来比」，立刻解锁「我想试试 v6 / 某个社区 prompt / 极简版」的对比。
2. **扩到 `dimensions.yaml` + 30 条分层用例**（第 5 条）：让「比什么」固定下来，之后比任何 prompt 都复用同一把尺。
3. **加 `dev-loop` profile**（第 6 条）：把现有方法从「一次性裁判」变成「迭代工具」——这才是真正「做出更好 prompt」的杠杆。

---

## 9. 附录：现有文件地图（本研究所据）

- 真源：`core/`（8 段）、`modules/`（6 模块）、`platform/`（4 工具 delta）
- 发布构建：`eval/prompts/v4.md`、`eval/prompts/v5.md`（由 `build_v5.py` 从顶层源重建）、`eval/prompts/v5_core`、`v5_modules`（冻结副本）
- 实验：`eval/{config.yaml, cases/cases.json, run.py, judge.py, report.py, freeze.py, build_v5.py, benchmark_lib.py, model_client.py, tests/test_benchmark.py}`
- 契约：`eval/SCORING_CONTRACT.md`、`eval/README.md`
- 历史研究：`00 Inbox/start-prompt-行业最佳实践结构调研.md`（LangGPT/Anthropic XML/七要素）、`00 Inbox/Start_Prompt_分析报告_vs_新版设计.md`（9 历史 prompt → v4 的设计推导）、`00 Inbox/Haisu_Universal_Start_Prompt_v4.md`

---

*注：本文是「方法研究」交付物，不是对 v4/v5 的实测结论。要得出「v4 还是 v5 更好」，需要按 `eval/README.md` 配置 4 个模型密钥并跑 development + holdout（需 API 调用）。本文给出的是让这种比较「对任意 Start Prompt 都可复用」的方法。*

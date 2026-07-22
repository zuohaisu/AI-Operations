# System Prompt（Start Prompt）行业最佳实践结构化调研报告

> 调研时间：2026年7月 | 调研范围：OpenAI / Anthropic / Google 官方指南 + 学术论文 + 社区最佳实践

---

## 一、结论先行

**"Start Prompt"（系统提示词/初始提示词）确实存在行业公认的最佳实践结构**，而且比 CO-STAR 等用户 Prompt 框架更加成熟和体系化。当前行业已经形成了以下共识：

| 维度 | 共识结论 |
|------|----------|
| **核心理念** | 结构化、模块化 — 像写代码一样写 System Prompt |
| **最主流框架** | **LangGPT**（中文社区） + **模块化架构**（学术/工业界） |
| **厂商推荐** | Anthropic 强推 XML 标签结构，OpenAI 和 Google 推荐分隔符分离 |
| **黄金模板** | Role → Context → Task → Constraints → Output Format → Examples → Workflow |
| **最佳实践来源** | Anthropic Claude 官方文档、LangGPT 框架、《The Prompt Report》(2024)、MPO 模块化优化 |

---

## 二、System Prompt vs User Prompt 框架

CO-STAR 是一个优秀的 **User Prompt 层面** 框架，但在实际工程中 **System Prompt 需要更完整、更工程化的结构**。两者的定位不同：

```
┌─────────────────────────────────────────────────────────────────┐
│  System Prompt（一次性设定，持久生效）                           │
│  ├── Role / Persona        角色 + 能力边界                      │
│  ├── Context / Background  领域知识、业务规则                    │
│  ├── Rules / Constraints   行为约束、安全边界                    │
│  ├── Skills / Capabilities 技能清单                             │
│  ├── Workflow / SOP        工作流程、标准操作程序                 │
│  ├── Output Format         输出格式规范                          │
│  └── Initialization        启动话术                              │
│                                                                  │
│  User Prompt（每次交互，临时的）                                 │
│  └── CO-STAR / CRISPE / APE 等框架 → 关注单次任务               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、行业主流 System Prompt 结构化框架

### 3.1 LangGPT — 中文社区最流行的结构化框架

由 **云中江树** 于 2023 年提出，GitHub 11,000+ Stars，已被主流大模型学进底层。是当前中文社区 **事实上的行业标准**。

**标准模板结构：**

```markdown
# Role: 角色名称

## Profile
- Author: 作者
- Version: 1.0
- Language: 中文
- Description: 角色描述与核心能力

### Skill-1
1. 具体技能描述
2. 预期行为

### Skill-2
1. ...

## Rules
1. 任何时候不要打破角色设定
2. 不要编造事实（防幻觉）
3. 输出约束规则

## Workflow
1. 分析用户输入 → 识别意图
2. 应用相关技能处理
3. 输出结构化结果

## Initialization
作为 <Role>，遵守 <Rules>，用 <Language> 与用户对话，问好并介绍 <Workflow>。
```

**关键设计理念：**
- **标识符**（`#`、`##`、`-`）实现层级结构，聚拢相同语义
- **属性词**（`Role`、`Skills`、`Rules`、`Workflow`）实现语义提示和归纳
- **变量引用**（`<Role>`、`<Rules>`）实现模块间联动
- 支持 Markdown / YAML / JSON 多种格式

### 3.2 Anthropic Claude 官方推荐 — XML 标签结构化

Claude 官方文档 **最强调结构化 System Prompt**，推荐使用 XML 标签作为顶级分隔方式：

```xml
<role>你是一位资深的Java架构师，擅长微服务设计和性能优化。</role>

<context>
我们的订单服务在高峰期 QPS 达到 5000，P99 延迟从 200ms 飙升到 2s。
当前架构：Spring Boot + MySQL 主从 + Redis 缓存。
</context>

<task>
分析可能的性能瓶颈，给出3个优先级最高的优化方案。
每个方案包含：问题定位、解决思路、预期效果、实施风险。
</task>

<constraints>
- 不考虑更换技术栈
- 方案需在 2 周内可落地
- 输出用 Markdown 表格
</constraints>

<output_format>
Markdown 表格，包含：方案名称 | 问题定位 | 解决思路 | 预期效果 | 实施风险
</output_format>
```

**Anthropic 的黄金法则：** 把你的 System Prompt 给一个对任务毫无背景的同事看——如果他会困惑，模型也会困惑。

### 3.3 学术/工业界共识 — 模块化架构

根据 EmergentMind 对学术界和工业界的综述研究，System Prompt 的通用模块化分类如下：

| 模块 | 英文名称 | 功能说明 |
|------|----------|----------|
| **角色/身份** | Role / Identity / Persona | 设定模型的领域专业性和输出风格 |
| **上下文/背景** | Context / Background | 封装领域知识、实时状态变量、场景情报 |
| **任务描述/目标** | Task / Goal / Objective | 明确可执行目标或推理终点 |
| **约束条件** | Constraints | 划定推理路径、资源限制、操作护栏 |
| **输出格式** | Output Format / Schema | 机器可读或人类友好的输出结构要求 |
| **示例** | Few-Shot Examples | 锚定风格、字段级格式和模式合规 |
| **工作流** | Workflow / SOP | 定义交互流程和步骤逻辑 |
| **初始化** | Initialization | 首次对话的启动行为定义 |

这七个模块构成了 **行业公认的 System Prompt 黄金模板**。

---

## 四、与 CO-STAR 框架的对比

CO-STAR 是用户 Prompt 层面的框架，而 System Prompt 需要一个更完整的结构：

| 对比维度 | CO-STAR（用户 Prompt） | System Prompt 结构化框架 |
|----------|----------------------|------------------------|
| **生命周期** | 单次交互 | 整个会话持久生效 |
| **关注点** | 一次任务的输入输出 | 模型整体行为模式 |
| **核心要素** | Context, Objective, Style, Tone, Audience, Response | Role, Profile, Skills, Rules, Workflow, Constraints, Output + Init |
| **复杂度** | 6个要素，轻量 | 7-10个模块，工程化 |
| **适用场景** | 营销邮件、产品公告等个性化任务 | Agent 构建、客服机器人、专业助手等生产级应用 |
| **版本管理** | 通常不涉及 | 需要 Git 版本控制（如 PromptVer） |

---

## 五、其他主流 Prompt Engineering 框架速查

以下框架可以叠加到 System Prompt 的不同模块中使用：

| 框架 | 全称 | 结构 | 适用场景 |
|------|------|------|----------|
| **CRISPE** | Context-Role-Intent-Style-Persona-Examples | 6要素 | 长文内容、品牌一致性要求高的任务 |
| **RAIL** | Rules-Action-Information-Limits | 4要素 | 编辑、摘要、安全敏感的快速任务 |
| **CLEAR** | Context-Language-Examples-Action-Review | 5要素 | 短文本编辑、微文案、带自检的任务 |
| **RASCEF** | Role-Action-Steps-Context-Examples-Format | 6要素 | 步骤明确的结构化任务 |
| **RISEN** | Role-Instructions-Steps-End goal-Narrowing | 5要素 | 需要明确最终目标和边界的任务 |
| **APE** | Action-Purpose-Expectation | 3要素 | 简单直接的任务（最轻量） |
| **TAG** | Task-Audience-Guardrails | 3要素 | 快速约束型任务 |
| **STAR** | Situation-Task-Action-Result | 4要素 | 从行为面试法改编，适合决策分析 |

---

## 六、行业最佳实践总结

### 6.1 六大核心原则（综合 OpenAI + Anthropic + Google 官方指南）

| 原则 | 说明 |
|------|------|
| ① **清晰明确，消除歧义** | 提供充分的上下文和约束，指定输出格式和长度 |
| ② **结构化组织，善用分隔符** | Anthropic 推 XML、OpenAI 多种混用、Google 推 XML/Markdown |
| ③ **提供 Few-Shot 示例** | 3-5个示例覆盖典型场景和边界情况 |
| ④ **给模型"思考时间"** | Chain-of-Thought，先推理再回答 |
| ⑤ **拆解复杂任务** | 意图分类 → 路由分发 → 流水线处理 |
| ⑥ **用参考文本减少幻觉** | 提供 Grounding 参考文本，要求标注来源 |

### 6.2 实用 Checklist（发布前逐项检查）

- [ ] **角色和背景** 是否明确定义
- [ ] **任务描述** 是否具体、无歧义
- [ ] **输出格式** 是否明确指定
- [ ] **约束条件** 是否完整列出
- [ ] 是否提供了 **Few-shot 示例**（至少3个）
- [ ] 长上下文是否遵循 **数据在前、指令在后**
- [ ] 是否使用了 **分隔符/标签** 区分不同内容块
- [ ] 复杂推理是否启用了 **CoT**（一步步思考）
- [ ] 是否包含 **自我验证** 步骤
- [ ] 是否对 **用户输入做了安全隔离**
- [ ] 是否建立了 **评估集** 进行回归测试
- [ ] 是否用 **正向指令** 替代了否定指令

### 6.3 安全防护建议

```
五层防御体系：
层次1 — 输入校验：长度限制、特殊字符过滤
层次2 — Prompt 加固：明确分隔用户输入和系统指令（XML标签包裹）
层次3 — 独立判断模型：用第二个 LLM 审查输入/输出
层次4 — 输出过滤：检查敏感信息泄露
层次5 — 最小权限：限制可调用的工具和数据范围
```

---

## 七、推荐实践路径

对于产品团队，建议采用以下路径构建 System Prompt：

```
第一步：选基础框架
└── 推荐 LangGPT 模板（中文生态最成熟）

第二步：补全核心模块
└── Role → Profile → Skills → Rules → Workflow → Initialization

第三步：注入领域知识
└── Context 模块中填充业务规则、数据口径、权限逻辑

第四步：添加安全护栏
└── Rules 模块中明确安全约束、用户输入隔离

第五步：建立评估集
└── 50+ 代表性用例，覆盖正常/边界/异常场景

第六步：迭代优化
└── 基于评估结果，局部调优各模块
```

---

## 八、参考资料

1. **LangGPT** — 结构化可复用提示词设计框架：[GitHub](https://github.com/langgptai/LangGPT) | [论文 arXiv:2402.16929](https://arxiv.org/abs/2402.16929)
2. **Anthropic Claude Prompt Engineering** — [官方文档](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
3. **The Prompt Report** — 提示词工程技术系统综述 [Schulhoff et al., 2024](https://www.emergentmind.com/papers/2406.06608)
4. **Modular Prompt Optimization (MPO)** — 模块化 Prompt 优化方法 [Sharma et al., 2026](https://www.emergentmind.com/papers/2601.04055)
5. **Structured System Prompts** — 结构化系统提示综述 [EmergentMind, 2026](https://www.emergentmind.com/topics/structured-system-prompt-summary)
6. **SPEAR Framework** — Prompt 代数与版本管理 [Cetintemel et al., 2025](https://www.emergentmind.com/papers/2508.05012)
7. **Prompt Engineering Frameworks (29+)** — [AiPromptsX](https://aipromptsx.com/prompts/frameworks)

---

> **核心结论：** System Prompt（Start Prompt）不仅有行业最佳实践的结构，而且比 CO-STAR 更加成熟和工程化。**LangGPT 的模块化模板 + Anthropic 的 XML 标签结构 + 模块化架构的七要素模型**，构成了当前行业最完整的 System Prompt 设计方法论。

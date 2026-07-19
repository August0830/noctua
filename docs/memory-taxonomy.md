# Noctua 记忆系统概念设计

> 基于 EverOS 三层记忆体系，适配 Noctua 自演进 Agent 场景

---

## 总览

EverOS 的记忆体系分为三大概念层，各自有不同的处理流程和持久化策略：

```
┌──────────────────────────────────────────────────┐
│                   EverOS 记忆体系                   │
├────────────────┬────────────────┬────────────────┤
│    用户记忆      │   Agent 记忆    │    知识 Wiki    │
│  (user memory)  │ (agent memory) │  (knowledge)   │
├────────────────┼────────────────┼────────────────┤
│ Episode        │ Case           │ Document       │
│ Profile        │ Skill          │ Topic          │
│ AtomicFact     │                │                │
│ Foresight      │                │                │
└────────────────┴────────────────┴────────────────┘
         ↓              ↓              ↓
┌──────────────────────────────────────────────────┐
│   Markdown (source of truth — Git 可版本化)        │
│   SQLite   (结构化索引 — 状态、队列、变更记录)         │
│   LanceDB  (向量索引 — 语义搜索、相似度检索)           │
└──────────────────────────────────────────────────┘
```

三种存储的关系：
- **Markdown**：人类可读、可编辑、可 Git diff。每一条记忆的 canonical 表达。
- **SQLite**：管理流水线状态（哪些消息已处理、哪些待 flush、Reflection 进度）。
- **LanceDB**：向量化索引，语义搜索和相似度匹配。

---

## 一、用户记忆（Human Memory）

记录开发者（mengzhilu）的知识、偏好、决策、计划。

### 1.1 Episode

**是什么：** 一次对话/事务/开发session的结构化摘要。

**处理流程：**
```
原始对话消息 
  → BoundaryDetector（切分话题边界，判断一个话题是否结束）
  → EpisodeExtractor（生成标题 + 摘要）
  → 写入 Markdown + LanceDB 索引
```

**示例：**
```
{"subject": "调研 Mindverse Mixture-of-LoRA 架构",
 "episode": "7月17日，mengzhilu 调研了 Mindverse 的 Macaron-V1-Preview，
            核心发现：749B参数模型仅用<300张卡，LoRA作为技能包热插拔，
            δ-mem 将记忆训进参数而非外挂记事本。"}
```

**Noctua 场景：** 每次调研讨论、技术决策、设计方案评审都是一个 Episode。

### 1.2 AtomicFact

**是什么：** 从 Episode 中拆出的最小独立事实单元，可单独检索。

**处理流程：**
```
Episode → AtomicFactExtractor → 拆为多个独立事实 → 各建向量索引
```

**示例：**
```
来源 Episode: "调研 Mindverse Mixture-of-LoRA"
  → AtomicFact: "Mixture-of-LoRA 支持一个底座挂载多个独立 LoRA 技能包"
  → AtomicFact: "δ-mem 用 8×8 在线记忆状态（+0.12% 参数）实现参数化记忆"
  → AtomicFact: "MinT 将引擎实时加载速度提升 8.5 倍"
```

**Noctua 场景：** 从设计讨论中提取可独立引用的技术事实，后续做 LoRA 训练数据筛选时按事实做质量校验。

### 1.3 Profile

**是什么：** 从多轮对话中推断出的用户画像（偏好、习惯、技能栈）。

**处理流程：**
```
多个 Episode → ProfileExtractor → 更新画像（增量 merge，不覆盖）
  ├── explicit_info: 用户明确说出的
  └── implicit_traits: 从行为推断的
```

**示例：**
```
{"implicit_traits": [
  {"category": "技术栈", "description": "Python + Go，关注 GPU 推理优化"},
  {"category": "偏好", "description": "本地部署优先于云服务"},
  {"category": "工作模式", "description": "白天调研设计，晚上跑实验"}
]}
```

**Noctua 场景：** Agent 可用 Profile 做个性化服务——比如优先推荐 Go 方案的 skill，跳过 Python 无关的优化建议。

### 1.4 Foresight

**是什么：** 用户明确或隐含的未来计划/意图。

**处理流程：**
```
Episode → ForesightExtractor → Foresight 记录（含时间窗口）
  → 到期未完成 → Sentinel 可触发主动提醒
```

**示例：**
```
{"content": "下周完成 verl-mint 训练环境搭建",
 "start_time": "2026-07-21", "end_time": "2026-07-27",
 "duration_days": 7, "evidence": "在调研 Mindverse 时明确提出"}
```

**Noctua 场景：** ROADMAP 里程碑自动追踪、实验计划到期提醒。

---

## 二、Agent 记忆（Agent Memory）

记录 Agent（Noctua）自身的执行轨迹和进化产物。

Agent 记忆与用户记忆的关键区别：
- **用户记忆**的主题是"人说了什么"（你是谁、你知道什么、你计划什么）
- **Agent 记忆**的主题是"Agent 做了什么"（执行了什么任务、怎么做的、结果如何）

### 2.1 Case

**是什么：** Agent 执行一次完整任务的轨迹记录：输入 → 工具调用序列 → 结果。

**处理流程：**
```
Agent 任务轨迹 
  → AgentBoundaryDetector（不同于用户的 BoundaryDetector，针对 Agent 轨迹优化）
  → AgentCaseExtractor（提取执行过程 + 成功/失败判定 + 关键决策点）
```

**示例：**
```
{"subject": "Rome GPU 调优 — H20 batch_size 搜索",
 "case": "任务：优化 Qwen3-0.6B 在 H20 上的 batch inference 吞吐
          步骤：1) 读 Roofline 数据 → compute-bound
                2) 设定 batch_size=32 → OOM on 8-GPU
                3) 降为 batch_size=16 → 通过，tokens/s ↑ 47%
                4) 写优化报告到 rubicon/data/results/
          结果：成功，吞吐从 1200 → 1764 tokens/s",
 "success": true,
 "cost": {"tokens": 12500, "wall_time_seconds": 180}}
```

**Noctua 场景：** Agent 每次执行 Rome 推理调优任务、Crucible 集测任务都记录为 Case。成功的 Case 形成经验，失败的 Case 形成教训。

### 2.2 Skill

**是什么：** 从多个成功 Case 中提炼的可复用执行流程/方法论。

**处理流程：**
```
多个成功 Case → AgentSkillExtractor → Skill（含适用条件、步骤、先决条件）
```

**示例：**
```
{"title": "H20 集群 batch inference 调优 SOP",
 "prerequisites": ["Roofline 数据已采集", "目标模型已部署"],
 "steps": [
   "1. 读 Roofline，判断 compute-bound vs memory-bound",
   "2. 如果是 compute-bound，优先增大 batch_size 到显存上限的 80%",
   "3. 如果是 memory-bound，优先调 radix_cache 和 prefix_caching",
   "4. 运行 sweep 实验（batch_size ∈ [4,8,16,32]），记录 tokens/s",
   "5. 输出优化报告到 rubicon/data/results/{model}_{date}.json"
 ],
 "applicable_models": ["Qwen3-0.6B", "Qwen3-8B", "Omni-397B"],
 "applicable_gpus": ["H20", "MI308X"],
 "success_rate": 0.92}
```

**Noctua 场景：** SkillForge 从 Agent 重复工作中自动提取并持续优化。高质量的 Skill → 训练数据 → **训进 LoRA 参数**，实现参数层内化。

---

## 三、知识 Wiki（Knowledge）

结构化领域知识，非对话产生的，而是来自已有文档。

### 3.1 Document

**是什么：** 一份知识文档（如设计文档、技术报告），自动解析 + 索引 + 分类。

**示例：**
```
rome/rubicon/docs/designs/ray-agentic-batch-inference.md
  → 解析后存入 Knowledge
  → Topic: "Agent 推理", "Ray 分布式", "Teacher-Student 蒸馏"
  → 可被 Agent 在任务执行时语义检索到
```

### 3.2 Topic

**是什么：** 知识文档的归类标签树，支持层级。

**示例：**
```
GPU 推理
  ├── 批处理调优
  ├── 缓存策略
  └── Roofline 模型
Agent 系统
  ├── 轨迹生成
  └── 自演进架构
LoRA 训练
  ├── Mixture-of-LoRA
  ├── verl-mint
  └── PEFT Scaling Law
```

---

## 四、离线进化：Reflection

三层记忆的增量提取只是第一步。Reflection 是定期运行的**离线整合进程**，让记忆越用越精炼：

```
Reflection 调度器定期运行：
  ├── 合并相似 Episode → 提炼更精炼的长期摘要
  ├── 合并相似 Profile trait → 去重 + 置信度加权
  ├── 合并相似 Case → 提炼更通用的 Skill
  ├── 过期 Foresight → 标记 resolved/expired
  └── 知识 Topic 层级重构 → 优化检索树
```

Reflection 是 EverMind "自演进"在记忆层的关键机制——不需要改模型参数，记忆自身通过整合变得越来越有用。

---

## 五、Noctua 场景映射

### 当前阶段（阶段 0-1）

```
Noctua 记忆池设计：
├── 用户记忆（关于 mengzhilu）
│   ├── Episode: 每次技术调研、设计讨论、方案决策
│   ├── AtomicFact: 罗列独立技术事实，支撑后续检索
│   ├── Profile: 开发偏好画像（Python/Go、GPU优化关注）
│   └── Foresight: ROADMAP 里程碑自动追踪
│
├── Agent 记忆（关于 Noctua Agent — 阶段 2 起）
│   ├── Case: Rome GPU 调优任务轨迹
│   ├── Case: Crucible 集测执行轨迹
│   ├── Skill: H20 batch 调优 SOP（可训进 LoRA）
│   └── Skill: 集测 YAML 生成模式
│
└── 知识 Wiki
    ├── Document: rome/rubicon/docs/ 下全部设计文档
    ├── Document: crucible/ 下的迁移规则和 skills
    ├── Topic: "GPU 推理优化"
    ├── Topic: "K8s 集测框架"
    ├── Topic: "LoRA 参数高效训练"
    └── Topic: "Agent 自演进评测"
```

### 关键设计原则

1. **用户记忆和 Agent 记忆隔离** —— 用户说的是"我想做什么"，Agent 做的是"我做了什么"。混淆会导致 Profile 被 Agent 轨迹污染。
2. **知识 Wiki 是只读参考** —— 来自已有文档，不参与对话提取管线。Agent 任务执行时按需检索。
3. **Skill 是进化的中间产物** —— 先作为 Markdown 存在，经过 Reflection 精炼后，成为 LoRA 训练数据的候选来源。
4. **Reflection 驱动进化闭环** —— 不是一次性提取，而是持续整合 → 精炼 → 淘汰过时信息。

---

## 参考

- EverOS：`github.com/EverMind-AI/EverOS`
- EverAlgo 概念文档：`everalgo/docs/concepts/architecture.md`
- EvoAgentBench 论文：`arXiv:2607.05202`
- Mindverse δ-mem：参数化记忆参考实现

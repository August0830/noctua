# Noctua：人-Agent 协同自演进系统设计

## 1. 概述

Noctua 是一个**自演进的 Agent 系统**，演进同时在两个层面发生：**参数层**（基于 LoRA 的模型微调）和**记忆层**（经验提取与技能复用）。系统设计为**领域无关**——Crucible 集测和 Rome Ray 推理部署是首批验证场景，但架构本身应当能以最小适配成本应用于任何新领域。

核心命题：

> Agent 的演进不能只发生在输入的 prompt 中，还应该发生在参数层。两层架构——参数演进（LoRA）+ 记忆演进（经验/技能提取）——构成完整的自改进闭环。人类在每个阶段的反馈不是中断，而是高质量的训练信号，推动渐进对齐。

### 1.1 项目名称

Noctua——小鸮属。象征静默观察中的智慧，持续适应，以及在未知黑暗中锐利的视野。

---

## 2. 架构：两层自演进

```
┌──────────────────────────────────────────────────────────────────┐
│                       Noctua 系统                                 │
│                                                                   │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐  │
│  │   第一层：参数演进         │    │   第二层：记忆演进            │  │
│  │                          │    │                              │  │
│  │  基座模型                 │    │  Agent 执行轨迹               │  │
│  │    ├── LoRA-技能-a       │    │    ├── Episode 提取           │  │
│  │    ├── LoRA-技能-b       │    │    ├── Case 提取              │  │
│  │    ├── LoRA-技能-c       │    │    ├── Skill 提取             │  │
│  │    └── ... (Mixture-of-  │    │    └── Reflection（离线       │  │
│  │         LoRA 路由)       │    │         记忆演化）            │  │
│  │                          │    │                              │  │
│  │  训练方式：               │    │  存储方式：                   │  │
│  │    verl-mint / GRPO      │    │    EverOS（Markdown +        │  │
│  │    DAPO / RL             │    │    SQLite + LanceDB）        │  │
│  │                          │    │                              │  │
│  │  参考：心洲科技          │    │  参考：EverMind              │  │
│  │  Mixture-of-LoRA [1]     │    │  生态体系 [2][3][4][5]       │  │
│  └─────────────────────────┘    └─────────────────────────────┘  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │               共享记忆池（EverOS）                            │ │
│  │                                                               │ │
│  │  开发者记忆 ←────→ Agent 运行时记忆                           │ │
│  │  (OpenCode 会话)      (Raven agent 轨迹)                     │ │
│  │                                                               │ │
│  │  跨工具、跨会话、用户所有、本地优先                            │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 第一层：参数演进（心洲科技路线）

**核心洞察来自 Mindverse（心洲科技）[1]：** Agent 的能力最终要回到模型训练本身，而不是靠 prompt 和框架拼出来。Mixture-of-LoRA 架构将每个 LoRA 视为独立的轻量「技能包」（仅占基座参数量的千分之几），可独立更新、运行时通过 router 动态组合，根据发现的一条 Scaling Law 扩展：`Accuracy ≈ a + b·ln(k)`，其中 k 是 LoRA 模块数量。

关键组件：

| 组件 | 作用 | 来源 |
|------|------|------|
| **Mixture-of-LoRA** | 一个底座上挂多个 LoRA 适配器，router 动态激活 | Mindverse Macaron-V1-Preview [1] |
| **δ-mem** | 记忆写进参数（8×8 显式状态，仅 +0.12% 参数），不依赖外挂记事本 | Mindverse [1] |
| **verl-mint** | LoRA RL 训练整合进字节跳动 verl 框架 | Mindverse + 字节跳动 verl [1] |
| **AReaL-MinT** | LoRA RL 训练整合进蚂蚁集团 AReaL 框架 | Mindverse + 蚂蚁集团 [1] |
| **MinT** | 百万量级 LoRA 策略寻址，加载速度提升 8.5×，训练到推理交接时间缩短到 1/18 | Mindverse [1] |
| **Agent Harness 同构训练** | 模型在训练阶段就接触真实部署环境——训练环境 = 部署环境，无迁移落差 | Mindverse [1] |

**为什么用 LoRA 而不是全参数微调：**

- 在大型 MoE 模型上，约 1/10 的训练成本达到与全参数训练同等的效果 [1]
- Thinking Machines Lab 在「LoRA Without Regret」中独立验证了同一结论 [1]
- 每个 LoRA 仅几 MB 到几百 MB——易于存储、分发和版本管理
- 无灾难性遗忘：新增 LoRA 不影响已有 LoRA
- 天然适合持续学习和个性化

### 2.2 第二层：记忆演进（EverMind 路线）

**核心洞察来自 EverMind [2][3]：** 记忆不应该是不断变长的外挂记事本。应该是三级记忆体系——用户记忆（Episodes, Profile, Foresight）、Agent 记忆（Cases, Skills）和知识 Wiki——配合离线「Reflection」在会话间隙持续重组和巩固记忆。

关键组件：

| 组件 | 作用 | 来源 |
|------|------|------|
| **EverOS** | 记忆运行时：Markdown + SQLite + LanceDB，本地优先，跨应用自演进 | EverMind-AI/EverOS（11.2k stars）[2] |
| **Raven** | 自改进 Agent Harness：Spine、SkillForge、Sentinel、Agent Templates | EverMind-AI/Raven（2.1k stars）[3] |
| **EverAlgo** | 算法库：边界检测、聚类、提取、排序（8 个分发包） | EverMind-AI/EverAlgo [4] |
| **SkillForge** | 检测可复用工作流，物化为技能，跟踪反馈，进化指令 | Raven 子系统 [3] |
| **Sentinel** | 主动引擎：监听事件、调度检查、评估提醒、路由行动 | Raven 子系统 [3] |
| **EvoAgentBench** | Agent 自演进评测：纵向增长曲线、迁移效率 | EverMind-AI/EvoAgentBench [5] |

### 2.3 为什么需要两层？

第一层（参数）和第二层（记忆）解决的是本质上不同的演进类型：

| 维度 | 第一层（LoRA） | 第二层（EverOS） |
|------|----------------|-------------------|
| **演进什么** | 模型权重（行为模式） | 显式知识（技能、案例、片段） |
| **速度** | 小时/天（训练） | 秒/分钟（提取） |
| **粒度** | 统计模式 | 符号化流程 |
| **迁移性** | 隐式（权重编码模式） | 显式（Markdown 技能可读可改） |
| **扩展性** | 准确率 ∝ ln(k) 个 LoRA | 检索质量 ∝ 提取质量 |
| **风险** | LoRA 间灾难性干扰 | 错误技能注入比没有技能更差 [5] |

第二层提供**快速、可解释**的演进。第一层提供**深层、隐式**的演进。两者构成完整闭环：第二层提取"什么有效"→ 第一层将其内化为权重 → 改进后的模型产出的轨迹更优质 → 第二层提取出更好的技能。

---

## 3. 人-Agent 协同工作流

工作流包含四个阶段，**三个角色**参与：

- **人（你）：** 开发者、审查者、对齐信号来源
- **OpenCode：** 编程助手——人的延伸，负责开发任务
- **Raven Agent：** 正在被构建的 Agent——自主执行领域任务

### 3.1 桥梁：EverOS 共享记忆池

OpenCode 和 Raven 通过 EverMe 插件共享同一个 EverOS 记忆池：

```bash
# 安装 EverMe + 各端插件
evercli plugin install opencode    # OpenCode → EverOS
# Raven 原生支持 EverOS，无需额外插件
```

这意味着：
- OpenCode 的开发决策被捕获为 EverOS episode
- Raven Agent 的执行轨迹被捕获为 EverOS case/skill
- 两端读写同一个记忆池
- Reflection 在离线状态下跨两个记忆源运行

### 3.2 阶段一：开发（人 + OpenCode）

```
你用 OpenCode 在 noctua/ 工作区中开发：

  活动：
  ├── 编写 Agent 逻辑、训练管线、评测代码
  ├── 配置 Raven Agent 模板
  ├── 为新领域设计 benchmark 用例
  └── Debug 与迭代

  输出到 EverOS：
  ├── 设计决策及理由（episode）
  ├── Bug 修复与解决方案（case）
  ├── 架构演进（知识 Wiki diff）
  └── →「开发者记忆」——对系统意图的理解
```

### 3.3 阶段二：运行（Raven Agent）

```
Raven Agent 执行领域任务：

  Crucible 集测场景：
  ├── 分析测试范围
  ├── 生成测试用例 YAML
  ├── 部署 testenv → 执行 → 监控
  ├── 分析结果 → 生成报告
  └── 失败时：使用 crucible 技能自动 debug

  Rome Ray 推理场景：
  ├── 解析部署需求
  ├── 生成 RayJob 配置
  ├── 配置 SGLang 参数
  ├── 提交任务 → 收集 UMonitor 指标
  └── 输出调优建议

  输出到 EverOS：
  ├── 执行轨迹（case）
  ├── 成功/失败模式（skill）
  ├── 用户交互与反馈（episode）
  └── →「运行时记忆」——对什么有效的理解
```

### 3.4 阶段三：反馈（EverOS Reflection）

```
EverOS Reflection（离线，在会话间隙运行）：

  来自开发者记忆：                   来自运行时记忆：
  ├── 设计意图                        ├── 执行结果
  ├── 架构约束                        ├── 失败模式
  └── 领域知识                        └── 用户修正

  Reflection 过程：
  ├── 合并 episode 聚类 → 精炼 profile
  ├── 提取可复用流程 → 物化为 skill
  ├── 识别训练信号 → 入队 LoRA 训练数据
  ├── 检测对齐偏移 → 标记人类审查
  └── 更新 Agent Template → 版本化部署

  产出：
  ├── SkillForge 建议技能（等待人类审查）
  ├── LoRA 训练数据集（自动积累）
  ├── 评测指标异常（告警）
  └── →「整合记忆」——可操作的、精炼后的知识
```

### 3.5 阶段四：迭代（LoRA 训练 + 重新部署）

```
人类审查反馈，触发迭代：

  1. 审查 SkillForge 建议：
     raven skill list --suggested --confidence 0.7

  2. 批准/拒绝/精炼技能：
     raven skill approve <skill-id>
     raven skill refine <skill-id> --reason "..."

  3. 用积累的数据触发 LoRA 训练：
     verl-mint train \
       --base-model Qwen3-235B \
       --lora-rank 8 \
       --data ./trajectories/batch_$(date +%Y%m%d).jsonl \
       --reward-model ./verifier/quality_scorer.py

  4. 部署新 LoRA + 更新后的 Agent 模板：
     raven agent-template deploy my-agent --version v0.3.0

  5. 关键节点人工确认 → 隐式 RLHF 训练信号
```

### 3.6 闭环总览

```
 ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
 │  阶段一  │────▶│  阶段二  │────▶│  阶段三  │────▶│  阶段四  │
 │  开发    │     │  运行    │     │  反馈    │     │  迭代    │
 │(OpenCode)│     │ (Raven)  │     │ (EverOS) │     │(LoRA+部署)│
 └──────────┘     └──────────┘     └──────────┘     └────┬─────┘
      ▲                                                  │
      └──────────────────────────────────────────────────┘
                     人类审查 + 批准
```

---

## 4. 对齐机制

> 执行正确是必要但不充分的。Agent 还必须能解释过程、论证决策、接受人类修正、并随时间收敛到人类意图。

### 4.1 三层对齐

```
第三层：决策对齐 ——「你为什么这么做？」
        ├── 每个动作附带自然语言理由
        ├── 可追溯来源：哪个 LoRA / 哪个历史案例 / 哪个技能
        └── 记录并说明放弃的替代方案

第二层：过程对齐 ——「你正在做什么？」
        ├── 分步执行，每步有明确检查点
        ├── 中间产物可见、可检查
        └── 人类可在任意检查点暂停、检查、修改、恢复

第一层：结果对齐 ——「你做对了吗？」
        ├── VerifierActor 自检（质量评分）
        ├── 关键决策点人类确认
        └── 审计面板汇总决策、风险和待审问题
```

### 4.2 基于检查点的执行

```yaml
# Agent 执行计划——自动生成，人类可审查
plan:
  steps:
    - id: "analyze-scope"
      description: "分析 Caesar RayCluster 扩展的测试范围"
      checkpoint: true          # 等待人类确认
      produces: "scope.json"
      
    - id: "generate-case"
      description: "生成 YAML 测试用例"
      checkpoint: false         # 自动推进
      produces: "testcase.yaml"
      reasoning: >
        基于 crucible-venti-test-caesar 中已有的 24 个 Caesar 迁移 case，
        VectorJob.PodTemplate 变更是新增场景。
        选择扩展模式而非新建 CRD 类型，以最小化 Controller 改动范围。
        来源：LoRA 'crucible-migration-patterns-v0.3'
        
    - id: "deploy-testenv"
      description: "部署测试环境"
      checkpoint: true          # 等待环境就绪确认
      produces: "env-status.json"
      
    - id: "execute-test"
      description: "执行测试并监控"
      checkpoint: false
      produces: "results.json"
      
    - id: "report"
      description: "生成测试报告"
      checkpoint: true          # 最终人类审查
      produces: "report.md"
```

### 4.3 决策追溯链

Agent 的每一个决策都必须可追溯：

```
决策：「使用 VectorJob 扩展模式，而非新建 CRD 类型」

  ├── 来源 LoRA：crucible-migration-patterns-v0.3
  │   └── 训练数据：worklog/checkpoints/ 中的 24 个 Caesar 迁移 case
  │
  ├── 相似历史决策：
  │   ├── worklog/checkpoints/007-caesar-migration.md —— 同一模式
  │   └── crucible-venti-test-caesar/testdata/ —— 先例 case
  │
  └── 放弃的替代方案：
      ├──「新建 CRD 类型」—— 放弃，理由：会不必要地扩大 Controller 改动范围
      └──「修改现有 WingsApp 定义」—— 放弃，理由：语义不匹配
```

### 4.4 结果审计面板

```
┌──────────────────────────────────────────────────────────┐
│ 任务：验证 Caesar RayCluster 扩展                        │
│ 状态：通过 ✅     步骤：5/5     检查点：3/3              │
├──────────────────────────────────────────────────────────┤
│ VerifierActor 自检：                                     │
│   ✅ 覆盖范围完整（24 个 case，0 遗漏）                  │
│   ✅ 无回归（所有已有 case 仍然通过）                     │
│   ✅ 新 case 符合 Crucible 惯例                          │
│   ⚠️  testcase.yaml:32 — 新字段语义需确认               │
├──────────────────────────────────────────────────────────┤
│ 需人工检查：                                              │
│   🔍 testcase.yaml:32 — 确认 VectorJob.PodTemplate 语义 │
│   🔍 results.json — 验证延迟在正常范围内                 │
├──────────────────────────────────────────────────────────┤
│ 可追溯决策：3 项                                          │
│   📋 扩展模式选择 — 来源：LoRA v0.3                      │
│   📋 跳过 webhook 测试 — 检查点处你已确认                │
│   📋 Batch size = 128 — 来源：rubicon/data/experiments   │
└──────────────────────────────────────────────────────────┘
```

### 4.5 人类修正作为训练信号

人类在检查点的操作自动被捕获为训练数据：

| 人类操作 | 训练信号 | 对 LoRA 的影响 |
|---------|---------|---------------|
| **确认** 检查点 | 正样本 | 强化对应 LoRA 技能 |
| **修改** Agent 输出 | 对比样本对 | DPO/GRPO——学习正确的替代方案 |
| **拒绝** 结果 | 负样本 | 衰减对应 LoRA 技能 |
| **补充理由** | 推理数据 | 追加到下一轮训练集 |

→ 每次检查点就是一次隐式 RLHF → 渐进对齐人类意图。

---

## 5. 评测方法论

基于 **EvoAgentBench [5]** 方法论，适配为领域无关使用。

### 5.1 核心原则（来自 EvoAgentBench）

1. **任何人都不能偷看答案。** 测试数据在训练期间密封。方法只能访问：题目、Agent 尝试了什么、是否成功。测试答案和成功的测试轨迹在演化期间不可见 [5]。

2. **训练和测试任务是相关的，不是随机的。** 任务按共享特征聚类（如知识工作的职业、软件问题的仓库、网络搜索的主题）。每个测试任务都有同簇内的训练任务支撑——如果方法没有帮助，不能归咎于测试数据不相关 [5]。

3. **每个格子都真实。** (agent, model, domain, method) 的每种组合都对照同一个无技能基线进行测量。无占位符、无选择性报告 [5]。

### 5.2 来自 EvoAgentBench 结果的三条警告

基于论文中 80 个实验配置的发现 [5]：

> ⚠️ **警告一——瓶颈是「记住了什么」，不是「怎么搜」。**
> 当技能有帮助时，是因为提取的内容有真正的结构，而不是因为搜索步骤更聪明了。调检索器、换 reranker、混合搜索——如果存储的技能本身模糊不清，这些都没用。把精力花在「该写什么」上 [5]。

> ⚠️ **警告二——不同问题看起来像但需要不同方法时，检索会误导。**
> 相似词汇在不同问题类型间出现，导致基于搜索的检索拉出错误技能，Agent 追随错误技能，在基线就能做对的题目上反而做错了。修复方法不是更好的检索器——而是给每个技能一个方式声明自己的适用范围 [5]。

> ⚠️ **警告三——不要默认注入技能。**
> 一个错误的技能可以让 Agent 在原本能做对的题目上做错。一个缺失的技能仅仅是维持原状。更安全的默认行为是「只在确信合适时才使用技能」，而不是「始终使用技能」[5]。

### 5.3 评测指标

| 指标 | 定义 | 来源 |
|------|------|------|
| **Δ 通过率** | 有技能 − 基线通过率 | EvoAgentBench [5] |
| **迁移效率** | Δ 通过率 / 训练 GPU-小时 | 自定义扩展 |
| **错误规避** | 重复错误模式减少率 | 受 EvoAgentBench 启发 |
| **技能命中质量** | 实际激活的技能数 / 可用技能数 | 自定义 |
| **成本变化** | 有/无技能时的 token 消耗比 | EvoAgentBench [5] |
| **解决轮次** | 完成任务的平均对话轮次 | EvoAgentBench [5] |
| **对齐得分** | 人类检查点接受率随时间的变化 | 自定义——渐进对齐指标 |
| **领域迁移** | 领域 A 学到的技能应用于领域 B 的 Δ | 自定义——领域无关验证 |

### 5.4 领域专用 Benchmark 模板

```yaml
# 任何新领域的模板
domain:
  name: "<领域名称>"
  description: "<Agent 需要完成什么>"
  
  clusters:
    - id: "<聚类-1>"
      description: "<共享特征>"
      train_samples: <N>
      test_samples: <M>
      baseline_model: "<模型ID>"
      
  metrics:
    - pass_rate_delta
    - transfer_efficiency
    - error_avoidance
    - skill_hit_quality
    - alignment_score
    
  constraints:
    train_test_separation: sealed    # 测试答案在训练期间不可见
    cluster_guarantee: true          # 每个测试任务都有同簇训练任务
    full_coverage: true              # 每个格子都测量，无选择性报告
```

### 5.5 首批 Benchmark 领域（示例）

```
领域 A：Crucible 集成测试
  按聚类：Controller 类型（WingsApp, VectorJob, MapJob...）
  成功 = 测试 case 通过 + 无回归 + 符合惯例

领域 B：Rome Ray 推理部署
  按聚类：模型系列（Qwen3, Omni...）、GPU 类型（H20, MI308X...）
  成功 = 部署成功 + 吞吐达标 + 错误率 < 阈值

领域 C：（未来）任意新领域
  按聚类：领域内在的任务分组方式
  成功 = 领域专用通过标准
```

---

## 6. 领域无关设计

> 系统不能硬编码为 Crucible 或 Rome。这些是初始验证领域。架构必须支持以最小适配成本接入任何新领域。

### 6.1 领域专属 vs. 领域无关

| 层面 | 领域专属 | 领域无关 |
|------|---------|---------|
| **Agent Harness** | — | Raven Spine、工具定义、上下文引擎 |
| **记忆** | 领域词汇、任务 Schema | EverOS episode/case/skill 结构 |
| **技能** | 任务流程（如「生成 Crucible YAML」） | SkillForge 提取协议 |
| **LoRA** | 在领域轨迹上微调 | LoRA 训练管线（verl-mint）、router |
| **评测** | 领域专属通过标准 | 评测协议、指标框架 |
| **对齐** | 检查点位置、领域风险 | 检查点机制、追溯链 |

### 6.2 领域接入协议

添加新领域只需定义：

```yaml
# domain-onboarding.yaml —— 新领域最小规格
domain:
  name: "my-new-domain"
  
  # 1. Agent 任务的输入输出形态
  task_schema:
    input_format: "<json|自然语言|文件>"
    output_format: "<期望输出>"
    tools_required:
      - "<工具-a>"
      - "<工具-b>"
    
  # 2. 如何为训练/测试划分做聚类
  clustering:
    strategy: "<按类型|按仓库|按主题|...>"
    cluster_field: "<字段名>"
    
  # 3. 成功标准
  pass_criteria:
    type: "<二元|评分|多指标>"
    definition: "<描述>"
    
  # 4. 检查点位置（用于对齐）
  checkpoints:
    - step: "<步骤ID>"
      reason: "<为什么此处需要人类审查>"
      
  # 5. 初始种子数据
  seed_data:
    trajectories: "<路径或空>"
    procedures: "<已有 SOP 路径>"
    knowledge: "<Wiki 文档路径>"
```

其余——EverOS 存储、SkillForge 提取、LoRA 训练管线、Raven Agent Harness、评测协议——全部领域无关，自动适配。

### 6.3 跨领域自修正

系统应该能检测领域专属技能的退化并自修正：

```
检测：
  ├── 评测指标低于基线
  ├── 人类在检查点的拒绝率上升
  └── SkillForge 检测到技能过时模式

自修正：
  ├── 标记受影响的 LoRA 模块待重训
  ├── 通过 Sentinel 提示人类：「技能 X 成功率下降 15%」
  ├── 自动从最近失败中入队新的训练数据
  └── 当信心低于阈值时回退到无技能基线
```

---

## 7. 组件栈

| 组件 | 项目 | 在 Noctua 中的角色 |
|------|------|-------------------|
| **Agent Harness** | Raven（EverMind） | Agent 运行时、Spine、上下文、主动引擎 |
| **记忆运行时** | EverOS（EverMind） | 共享记忆池、Markdown 原生、本地优先 |
| **记忆算法** | EverAlgo（EverMind） | 提取、聚类、排序 |
| **LoRA 训练** | verl-mint / AReaL-MinT | 基于 Agent 轨迹的 RL LoRA 训练 |
| **LoRA 推理** | SGLang（multi-LoRA batching） | 多 LoRA 适配器推理 |
| **基座模型** | Qwen3 / GLM5.1 / 等 | 底层基础模型 |
| **开发工具** | OpenCode | 人类编程助手，喂入 EverOS |
| **分布式计算** | Ray + KubeRay | 训练和推理基础设施 |
| **GPU 调度** | Caesar（Augustus） | 工作负载编排（Rome 场景） |
| **测试框架** | Crucible | 集成测试（Crucible 场景） |
| **个人记忆** | EverMe | 跨设备、跨 Agent 个人记忆 |

---

## 8. 参考文献

1. **Mindverse（心洲科技）Macaron-V1-Preview 与 Mixture-of-LoRA 架构。**
   John Yin（尹John），「美团投了一家只有不到 300 张卡的 AI 公司」，微信公众号文章，2026。
   https://mp.weixin.qq.com/s/2nhlPKYZjpmXpU8Ky6rTuQ
   - 核心概念：Mixture-of-LoRA、δ-mem、MinT、Agent Harness 同构训练、
     Scaling Law Accuracy ≈ a + b·ln(k)、verl-mint、AReaL-MinT
   - Mind Lab 技术博客：https://macaron.im/mindlab

2. **EverOS —— 记忆运行时。**
   EverMind-AI/EverOS，GitHub，Apache-2.0，11.2k stars。
   https://github.com/EverMind-AI/EverOS
   - Markdown 原生、本地优先、SQLite + LanceDB
   - 三种记忆类型：用户记忆（Episodes, Profile, Foresight）、
     Agent 记忆（Cases, Skills）、知识 Wiki
   - 离线 Reflection 实现记忆演化

3. **Raven —— 自改进 Agent Harness。**
   EverMind-AI/Raven，GitHub，Apache-2.0，2.1k stars。
   https://github.com/EverMind-AI/Raven
   - Spine 架构、SkillForge、Sentinel、Agent Templates
   - 12 种消息网关适配器、原生 TUI

4. **EverAlgo —— 算法库。**
   EverMind-AI/EverAlgo，GitHub，Apache-2.0。
   https://github.com/EverMind-AI/EverAlgo
   - 8 个分发包：core、boundary、clustering、rank、parser、
     user-memory、agent-memory、knowledge

5. **EvoAgentBench —— Agent 自演进评测。**
   Gao et al.，「EvoAgentBench: Benchmarking Agent Self-Evolution via
   Ability Transfer」，arXiv:2607.05202，2026。
   https://arxiv.org/abs/2607.05202
   - 5 个领域、528/267 训练/测试划分、80 个实验配置
   - 关键发现：瓶颈是提取质量而非检索；
     错误技能注入比没有技能更差；相似词汇误导检索

6. **Rome/rubicon —— GPU 推理优化研究。**
   内部工作区：`/Users/mengzhilu.mzl/Desktop/working/rome/rubicon`
   - `docs/designs/ray-agentic-batch-inference.md`（1117 行）：
     Teacher-Student 蒸馏的 5 个 Ray Actor 角色，
     引用 Mixture-of-LoRA 和 MinT
   - `docs/designs/sft-on-ray.md`（292 行）：
     LoRA + Ray Train 管线设计，4 种训练模式
   - `docs/designs/ray-construction-plan/`：
     跨团队 Ray 统一基础设施计划

7. **Crucible —— Kubernetes 集成测试框架。**
   内部工作区：`/Users/mengzhilu.mzl/Desktop/working/crucible`
   - YAML 驱动测试引擎、基于 CEL 的断言
   - Agent 技能体系、工作日志惯例、反思协议
   - 从旧框架迁移（venti-test, caesar-asi-test）

8. **Thinking Machines Lab ——「LoRA Without Regret」。**
   独立验证：在大型 MoE 模型上 LoRA RL 达到与全参数训练等效的性能，
   成本约 1/10。引用于 [1]。

9. **FireAct —— 通过微调训练 Agent。**
   Andrew Chen 与 Shunyu Yao 等，2023。
   基础性工作，论证 Agent 能力应来自模型训练而非 prompt 工程。引用于 [1]。

10. **姚顺雨 ——「智能下半场」。**
    论证构建有意义的 Benchmark 可能是打造模型最重要的事。引用于 [1]。

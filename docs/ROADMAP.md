# Noctua 路线图

> 状态：阶段 0（基础设施搭建）—— 2026-07-17

## 图例

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成
- `P0` 关键路径
- `P1` 重要，可并行
- `P2` 锦上添花

---

## 阶段 0：基础设施搭建

**目标：** 所有基础设施组件运行起来，共享记忆池建立，开发工作流可用。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 0.1 | 安装 EverOS，运行 `everos demo`，验证记忆管线 | P0 | `[x]` | — |
| 0.2 | 安装 Raven，运行 `raven onboard`，验证 Agent Harness | P0 | `[x]` | — |
| 0.3 | 安装 EverMe CLI，运行 `evercli auth login` | P0 | `[x]` | — |
| 0.4 | 配置 EverMe → OpenCode 插件（`evercli plugin install opencode`） | P0 | `[x]` | 0.3 |
| 0.5 | 验证跨工具记忆：OpenCode → 本地 EverOS 写入链路打通 | P0 | `[x]` | 0.4 |
| 0.6 | 搭建 noctua 项目结构：`src/`、`tests/`、`configs/`、`skills/` | P1 | `[x]` | — |
| 0.7 | 编写开发者环境文档 `CONTRIBUTING.md` | P1 | `[ ]` | 0.6 |
| 0.8 | 验证 EverOS 对 `rome/` 和 `crucible/` 软链的只读访问 | P1 | `[x]` | — |

**完成标准：**
- EverOS 服务本地运行，记忆写入/搜索正常
- Raven TUI 可启动，基础 Agent 循环可用
- OpenCode 会话被捕获进 EverOS
- Raven 可读取 OpenCode 写入的记忆

---

## 阶段 1：记忆层

**目标：** EverOS 配置为结构化 Agent 记忆。从已有工作日志灌入种子数据。SkillForge 提取管线可运行。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 1.1 | 设计 Noctua 记忆分类法：episode、case、skill、知识页面 | P0 | `[x]` | 0.5 |
| 1.2 | 灌入 Crucible 种子数据：工作日志检查点、迁移规则、技能 | P0 | `[~]` | 1.1 |
| 1.3 | 灌入 Rome 种子数据：设计文档、实验结果、调优手册 | P0 | `[~]` | 1.1 |
| 1.4 | 配置 Noctua 专用 EverOS Reflection（自定义整合调度） | P1 | `[ ]` | 1.1 |
| 1.5 | 实现领域无关的 episode → case 提取管线 | P1 | `[ ]` | 1.1 |
| 1.6 | 实现 SkillForge 从重复 Agent 工作流中提取技能 | P1 | `[ ]` | 1.5 |
| 1.7 | 测试 Crucible 和 Rome 领域间记忆检索不交叉污染 | P1 | `[ ]` | 1.2, 1.3 |
| 1.8 | 实现记忆质量评分：提取的技能有用还是模糊？（警告一 [5]） | P2 | `[ ]` | 1.6 |

**完成标准：**
- Crucible 工作日志和 Rome 设计文档在 EverOS 中可搜索
- Reflection 运行并产出整合记忆
- SkillForge 从已有数据中检测到至少一个可复用流程
- 记忆检索按领域正确隔离

**参考文献：** EverOS [2]、EverAlgo [4]、EvoAgentBench 警告一 [5]

---

## 阶段 2：Agent Harness

**目标：** Raven Agent 自主执行 Crucible 集测和 Rome 推理任务，带检查点对齐的闭环。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 2.1 | 定义 Crucible 测试场景的 Raven Agent Template | P0 | `[x]` | 1.2 |
| 2.2 | 定义 Rome 推理场景的 Raven Agent Template | P0 | `[x]` | 1.3 |
| 2.3 | 实现检查点执行协议（YAML plan → steps → checkpoints） | P0 | `[x]` | — |
| 2.4 | 实现决策追溯链（每个动作 → 来源 LoRA/技能/历史） | P0 | `[ ]` | 2.3 |
| 2.5 | 实现步骤级中断/恢复（人类在检查点暂停） | P1 | `[ ]` | 2.3 |
| 2.6 | 将 Crucible 测试运行器集成到 Raven Agent 工具 | P0 | `[ ]` | 2.1, 2.3 |
| 2.7 | 将 Rome Ray Job 提交/监控集成到 Raven Agent 工具 | P0 | `[ ]` | 2.2, 2.3 |
| 2.8 | 端到端运行 Crucible 测试场景（人类在环） | P1 | `[ ]` | 2.6 |
| 2.9 | 端到端运行 Rome 推理场景（人类在环） | P1 | `[ ]` | 2.7 |
| 2.10 | 使用 Crucible debug-case 技能实现失败自动诊断 | P2 | `[ ]` | 2.6 |

**完成标准：**
- Raven Agent 能为给定场景生成有效的 Crucible 测试用例 YAML
- Raven Agent 能成功提交 RayJob 并收集指标
- 人类可在每个检查点检查、修改、批准
- 每个 Agent 动作的决策追溯被记录

**参考文献：** Raven [3]、crucible/.agents/skills/crucible-dev、crucible/.agents/skills/debug-case、rome/rubicon/docs/designs/ray-agentic-batch-inference.md

---

## 阶段 3：对齐机制

**目标：** 人类在检查点的反馈被系统化捕获为训练信号。对齐得分追踪随时间的收敛。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 3.1 | 实现 VerifierActor 质量评分（基于 Rome 设计） | P0 | `[ ]` | 2.3 |
| 3.2 | 实现人类检查点操作捕获：确认 / 修改 / 拒绝 / 补充理由 | P0 | `[ ]` | 2.4 |
| 3.3 | 实现操作→训练数据转换器（确认→正样本、修改→DPO pair、拒绝→负样本） | P0 | `[ ]` | 3.2 |
| 3.4 | 实现审计面板：汇总 + 自检结果 + 可追溯决策 + 待审问题 | P1 | `[ ]` | 2.4, 3.1 |
| 3.5 | 实现对齐得分指标（人类检查点接受率随时间的变化） | P1 | `[ ]` | 3.3 |
| 3.6 | 实现 Sentinel 对齐偏移告警（拒绝率飙升） | P2 | `[ ]` | 3.5 |
| 3.7 | 测试完整对齐闭环：Agent 执行 → 人类修正 → 训练数据生成 → LoRA 训练 → Agent 改进 | P1 | `[ ]` | 3.3, 4.3 |

**完成标准：**
- VerifierActor 在每次 Agent 任务后运行并给出质量分数
- 人类修正被捕获为结构化训练记录
- 审计面板在每次任务完成后渲染
- 对齐得分可测量且有变化趋势

**参考文献：** rome/rubicon/docs/designs/ray-agentic-batch-inference.md（VerifierActor）、Raven Sentinel [3]、design.md §4 对齐机制

---

## 阶段 4：参数演进

**目标：** LoRA 训练管线运行。Agent 轨迹 → 训练数据 → LoRA 适配器 → 运行时 router 激活。完成第一个参数层自演进循环。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 4.1 | 搭建 verl-mint 训练环境（基于 Mindverse/字节跳动集成） | P0 | `[ ]` | — |
| 4.2 | 实现轨迹→LoRA 训练数据转换器（格式、质量过滤） | P0 | `[ ]` | 3.3 |
| 4.3 | 训练第一个 LoRA：Crucible 测试用例生成（种子数据来自阶段 1+2） | P0 | `[ ]` | 4.1, 4.2, 2.8 |
| 4.4 | 训练第一个 LoRA：Rome 推理调优（种子数据来自阶段 1+2） | P0 | `[ ]` | 4.1, 4.2, 2.9 |
| 4.5 | 实现 Mixture-of-LoRA 路由：领域检测 → LoRA 选择 → 激活 | P0 | `[ ]` | 4.3, 4.4 |
| 4.6 | 将 LoRA 路由集成到 Raven Agent 运行时 | P0 | `[ ]` | 4.5, 2.6 |
| 4.7 | 验证：带 LoRA 的 Agent 在 Crucible 任务上优于基线 | P0 | `[ ]` | 4.6, 5.6 |
| 4.8 | 验证：带 LoRA 的 Agent 在 Rome 任务上优于基线 | P0 | `[ ]` | 4.6, 5.6 |
| 4.9 | 实现 LoRA 信心评分（警告三 [5]：不要默认注入） | P1 | `[ ]` | 4.5 |
| 4.10 | 实现 LoRA 适用范围声明（警告二 [5]） | P1 | `[ ]` | 4.5 |
| 4.11 | 实现 δ-mem 风格参数化记忆（远期目标） | P2 | `[ ]` | 4.7 |

**完成标准：**
- verl-mint 训练管线用 Agent 轨迹数据端到端运行
- LoRA 适配器加载到 SGLang 推理，multi-LoRA batching 工作
- Router 在运行时正确选择领域对应的 LoRA
- Crucible 和 Rome 两个领域的 Δ 通过率 > 0

**参考文献：** Mindverse Mixture-of-LoRA [1]、δ-mem [1]、verl-mint [1]、AReaL-MinT [1]、MinT [1]、EvoAgentBench 警告二和警告三 [5]、rome/rubicon/docs/designs/sft-on-ray.md

---

## 阶段 5：评测框架

**目标：** 基于 EvoAgentBench 方法论的领域无关评测框架。基线已测量，技能/LoRA 提升已量化，对齐已追踪。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 5.1 | 实现评测协议引擎（训练→提取→评测，密封测试数据） | P0 | `[ ]` | — |
| 5.2 | 构建 Crucible Benchmark：聚类测试用例、训练/测试划分、通过标准 | P0 | `[ ]` | 2.6 |
| 5.3 | 构建 Rome Benchmark：聚类部署场景、训练/测试划分、通过标准 | P0 | `[ ]` | 2.7 |
| 5.4 | 实现指标采集器：Δ 通过率、迁移效率、错误规避、技能命中质量、成本变化、解决轮次 | P0 | `[ ]` | 5.1 |
| 5.5 | 实现对齐得分采集器（来自阶段 3） | P0 | `[ ]` | 3.5, 5.4 |
| 5.6 | 运行基线测量：Crucible + Rome 测试集上的无 LoRA Agent | P0 | `[ ]` | 5.2, 5.3, 5.4 |
| 5.7 | 运行带技能测量：Crucible + Rome 测试集上的带 LoRA Agent | P0 | `[ ]` | 4.7, 4.8, 5.6 |
| 5.8 | 实现排行榜可视化（领域 × 模型 × 方法 → Δ） | P1 | `[ ]` | 5.4 |
| 5.9 | 实现领域接入 Benchmark 生成器（YAML 规格 → Benchmark） | P1 | `[ ]` | 5.1 |
| 5.10 | 运行纵向测量：在 5 个以上 LoRA 训练周期中追踪 Δ | P2 | `[ ]` | 5.7 |

**完成标准：**
- 评测运行产出每个领域的 Δ 通过率、迁移效率、错误规避
- Crucible 和 Rome 基线已记录
- 带 LoRA 结果相比基线有可测量的提升
- 排行榜可渲染（文本版 MVP 可接受）

**参考文献：** EvoAgentBench 论文 [5]、EvoAgentBench 排行榜 https://evermind-ai.github.io/EvoAgentBench/

---

## 阶段 6：领域无关验证 + 自修正

**目标：** 系统仅需一份 YAML 接入规格即可适配任何新领域。自修正机制检测并修复退化。

| ID | 任务 | 优先级 | 状态 | 依赖 |
|----|------|--------|------|------|
| 6.1 | 设计领域接入 YAML schema（任务 schema、聚类、通过标准、检查点、种子数据） | P0 | `[ ]` | 5.9 |
| 6.2 | 实现从接入 YAML 自动生成 Benchmark | P1 | `[ ]` | 6.1, 5.9 |
| 6.3 | 实现新领域自动技能提取（前 N 条轨迹 → 技能） | P1 | `[ ]` | 6.1 |
| 6.4 | 实现新领域自动 LoRA 训练触发（积累足够轨迹后） | P2 | `[ ]` | 6.3, 4.2 |
| 6.5 | 实现自修正检测：指标下降、拒绝率上升、技能过时 | P1 | `[ ]` | 5.6 |
| 6.6 | 实现自修正响应：标记 LoRA、入队重训数据、回退基线 | P2 | `[ ]` | 6.5 |
| 6.7 | 用**第三个领域**（非 Crucible、非 Rome）验证 —— 证明领域无关 | P0 | `[ ]` | 6.2, 6.3 |
| 6.8 | 编写面向外部贡献者的领域接入指南 | P2 | `[ ]` | 6.7 |

**完成标准：**
- 一个新领域可通过单份 YAML 文件接入
- Agent 在 3 个训练周期内开始在新领域产出有用结果
- 自修正检测到指标退化并做出响应
- 第三个领域验证结果与 Crucible/Rome 可比

---

## 依赖关系图

```
阶段 0 ──▶ 阶段 1 ──▶ 阶段 2 ──▶ 阶段 3 ──▶ 阶段 4 ──▶ 阶段 5 ──▶ 阶段 6
                                      │                         │
                                      └───────────┬─────────────┘
                                                  │
                                    （阶段 3 反馈 → 阶段 4 训练）
                                                  │
                                    （阶段 4 结果 → 阶段 5 评测）
                                                  │
                                    （阶段 5 指标 → 阶段 6 自修正）
```

并行化机会：
- 阶段 1 中 1.2（Crucible 种子）和 1.3（Rome 种子）可并行
- 阶段 2 中 2.1-2.5（Harness）和 2.6-2.7（领域工具）可并行
- 阶段 4 中 4.3（Crucible LoRA）和 4.4（Rome LoRA）可并行
- 阶段 5 中 5.2（Crucible Benchmark）和 5.3（Rome Benchmark）可并行

---

## 关键风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| EverOS + Raven 兼容性问题 | 阶段 0 受阻 | 先用独立 EverOS；Raven 先用 headless/CLI 模式 |
| LoRA 训练需要 GPU，本地不可用 | 阶段 4 受阻 | 通过 Caesar 使用远程 H20 集群（Rome 基础设施）；先用极小 LoRA rank |
| 错误技能注入导致性能下降（警告三 [5]） | 阶段 4 结果为负 | 实现信心阈值；回退到无技能基线 |
| 人类反馈量不足以有效训练 | 阶段 3 停滞 | 从 VerifierActor 分数合成训练对；用检查点确认作为密集信号 |
| 新领域接入过于复杂 | 阶段 6 失败 | 将接入规格减到最小；用 LLM 从描述自动生成领域 YAML |

---

## 参考文献（同 design.md §8）

1. Mindverse Macaron-V1-Preview 与 Mixture-of-LoRA [微信公众号文章，2026]
2. EverOS [EverMind-AI/EverOS，11.2k stars]
3. Raven [EverMind-AI/Raven，2.1k stars]
4. EverAlgo [EverMind-AI/EverAlgo]
5. EvoAgentBench [arXiv:2607.05202，2026]
6. Rome/rubicon 内部工作区
7. Crucible 内部工作区
8.「LoRA Without Regret」[Thinking Machines Lab]
9. FireAct [Chen & Yao，2023]
10.「智能下半场」[姚顺雨]

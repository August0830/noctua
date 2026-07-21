# Noctua Agent Context

> OpenCode 新 session 进入 noctua 目录时自动加载。

## 项目概述

Noctua 是一个自演进 Agent 框架。核心理念：Agent 的每次执行都产出可积累的训练数据，通过记忆层（EverOS）和参数层（LoRA）实现持续改进。

## 核心工作流

每个任务遵循 **Plan → Execute → Verify → Feedback → Training Data** 闭环：

### 1. Plan（计划任务）

创建 YAML 计划文件，定义步骤和检查点：

```yaml
# configs/plans/<task-name>.yaml
plan_id: "rome-h20-optimize-20260720"
domain: rome
agent_template: rome
steps:
  - id: "collect-baseline"
    type: auto
    tool: read_metrics
  - id: "review-baseline"
    type: checkpoint       # ← 暂停等人批准
    checkpoint:
      approval: required
```

完整协议见 `docs/checkpoint-protocol.md`，Python 模型见 `src/noctua/agent/protocol.py`。

### 2. Execute（执行）

使用 Raven Agent 执行计划。Agent Template 定义了人格和工具规则：

- **Rome Agent** (`configs/agent-templates/rome/`) — GPU 推理优化
  - Roofline 分析 → 单变量扫描 → 多变量验证 → 生产上线建议
  - 检查点：生产配置修改、RayJob 提交到生产集群
  
- **Crucible Agent** (`configs/agent-templates/crucible/`) — K8s 集成测试
  - 生成 YAML 用例 → 部署环境 → 执行测试 → 五层诊断
  - 检查点：环境创建/销毁、集群修改

执行命令：
```bash
raven agent -m "按 Rome Agent Template 分析 rome/rubicon/data/results/ 下的实验结果"
```

### 3. Verify（质量评分）

VerifierActor（`src/noctua/eval/verifier.py`）以 LLM-as-Judge 模式对 Agent 产出评分：

| 维度 | Rome 场景 | Crucible 场景 |
|------|----------|-------------|
| correctness | 指标计算是否正确 | YAML 约定是否正确 |
| efficiency | 分析是否冗余 | N/A |
| factuality | 数字是否可溯源 | 诊断是否有据 |
| completeness | 是否覆盖 L1/L2/L3 | 是否覆盖五层诊断 |

产出 `quality_score (0-1)` + `usable_for_sft` (可做训练数据？) + 5-class 轨迹分类。

### 4. Feedback（人类审查 + 落盘）

检查点处人类决策被捕获（`src/noctua/align/feedback.py`）：

| 操作 | 含义 | 训练信号类型 |
|------|------|------------|
| approve | 正确 | positive（正样本） |
| modify + 新参数 | 接近但不精确 | DPO pair（偏好学习） |
| reject + 理由 | 错误 | negative（负样本） |

全程轨迹通过 EverOS 落盘：
- 成功的执行 → `agent_case`（怎么做的）
- 重复模式 → `agent_skill`（可复用流程，由 SkillForge 提取）
- 关键指标 → `atomic_fact`（可独立检索）

### 5. Training Data（训练数据生成）

`feedback_to_signals()` 将 FeedbackSession 转为 `TrainingSignalBatch`，供阶段 4 LoRA 训练使用。格式见 `src/noctua/align/feedback.py`。

## 记忆体系

EverOS 三层记忆（详见 `docs/memory-taxonomy.md`）：

| 记忆类型 | 内容 | 例子 |
|---------|------|------|
| Episode | 发生了什么 | "今天用 flashinfer 跑了一次 attention backend 扫参" |
| AtomicFact | 独立事实 | "flashinfer 比 mixedattn 快 18%" |
| Profile | 用户画像 | "关注 GPU 调优，偏好 Ray 框架" |
| Foresight | 未来计划 | "下周完成 verl-mint 环境搭建" |
| Agent Case | Agent 执行轨迹 | "调优任务的完整 tool 调用序列" |
| Agent Skill | 可复用流程 | "H20 batch 调优 SOP" |
| Knowledge | 文档 | rome/ 和 crucible/ 下的 .md 文件 |

## 关键命令

```bash
# 启动 EverOS（后台）
source .venv/bin/activate
python scripts/run_everos.py server start &

# 检查服务
curl http://127.0.0.1:8000/health

# 运行 Raven Rome Agent（需要先配置 API keys）
export EVEROS_LLM__API_KEY="sk-..."
export EVEROS_EMBEDDING__API_KEY="sk-..."
raven agent -m "<你的任务>"

# 导入种子数据
python scripts/import_knowledge_seed.py   # 知识文档 → Knowledge Wiki
python scripts/import_memory_seed.py      # 工作日志 → Episode/Case

# 检查 EverOS 队列
python -m everos.entrypoints.cli.main cascade status

# 写入记忆（MCP 插件自动调用，也可手动）
curl -X POST http://127.0.0.1:8000/api/v1/mem/personal \
  -H 'Content-Type: application/json' \
  -d '{"conversationId":"manual-001","messages":[...]}'

# 搜索记忆
curl -X POST http://127.0.0.1:8000/api/v1/mem/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"flashinfer 性能对比","topK":5}'
```

## 新增任务的标准流程

在 noctua 下新开 OpenCode session 后，要做 Rome 或 Crucible 相关任务：

1. **了解上下文** — 读 `docs/ROADMAP.md` 当前阶段、`docs/memory-taxonomy.md` 记忆体系
2. **创建 Plan** — 在 `configs/plans/` 下写 YAML（参考 `rome-mvp-v1.example.yaml`）
3. **执行** — 用 `raven agent -m "..."` 或手动步骤
4. **记录** — 将产出通过 `mem_save_fact`（关键结果）和 `mem_save_turn`（完整轨迹）存入 EverOS
5. **审查** — 运行 VerifierActor 评分，人类在检查点确认/修改/拒绝
6. **积累** — 训练信号自动生成，积累到阈值触发 LoRA 训练（阶段 4）

## 环境依赖

- Python 3.12+（uv 管理）
- EverOS 1.1.3+（记忆服务）
- Raven 0.1.6+（Agent Harness）
- EverMe CLI（连接 OpenCode）
- DeepSeek API Key（LLM）
- 硅基流动 API Key（Embedding + Rerank）

## 只读数据源

软链 `rome/` 和 `crucible/` 指向外部工作目录。Agent 可读但不可写：
- `rome/rubicon/data/` — 实验数据、Roofline
- `rome/rubicon/docs/` — 设计文档、报告
- `crucible/testdata/` — 测试用例
- `crucible/.agents/skills/` — Agent Skill 参考

## 当前状态

阶段 0-3 完成。阶段 4（LoRA 训练）待 GPU 资源就绪后启动。
详见 `docs/ROADMAP.md`。

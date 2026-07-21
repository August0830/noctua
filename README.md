# Noctua — 自演进 Agent 系统

基于 **EverMind 记忆层演进 + 开源 LoRA 参数层演进** 的自演进 Agent 框架。
演进同时发生在 prompt 层（记忆检索 + 技能复用）和参数层（LoRA 微调 + 路由激活）。

## 核心理念

```
传统 Agent:  LLM + tools + loop → 跑一次丢一次
Noctua:     LLM + tools + loop → 轨迹落盘 → 记忆精炼 → LoRA 参数内化 → 越用越聪明
```

## 工作流

```
Plan（计划任务） → Execute（Agent 执行） → Verify（质量评分 + 人类审查）
                                                ↓
Training Data ← Feedback（确认/修改/拒绝） ← Checkpoint（检查点暂停）
      ↓
LoRA Training → Router 激活 → Agent 下次执行时自动使用

全程 EverOS 记录：episode（发生了什么）→ case（怎么做的）→ skill（可复用流程）
```

## 三层演进架构

| 层 | 机制 | 技术栈 |
|----|------|--------|
| **记忆层** | 轨迹存储 → 提取 → Reflection 离线精炼 | EverOS (Markdown + SQLite + LanceDB) |
| **参数层** | 技能训进 LoRA → Mixture-of-LoRA 路由 | Ray Train + verl-mint + SGLang multi-LoRA |
| **Agent 层** | Plan 驱动的检查点执行，人类在环 | Raven + Agent Templates + Checkpoint Protocol |

## 目录结构

```
noctua/
├── docs/                          # 设计文档
│   ├── ROADMAP.md                 # 六阶段路线图（当前：阶段 3 完成）
│   ├── design.md                  # 系统设计总文档
│   ├── memory-taxonomy.md         # EverOS 三层记忆体系说明
│   ├── checkpoint-protocol.md     # 检查点执行协议规范
│   └── architecture-memory.md     # 本地存储架构
├── src/noctua/                    # Python 源码
│   ├── agent/                     # Agent 层：protocol + trace
│   ├── align/                     # 对齐层：feedback → TrainingSignal
│   ├── eval/                      # 评测层：VerifierActor 质量评分
│   ├── memory/                    # 记忆层（规划中）
│   └── lora/                      # LoRA 训练层（规划中）
├── configs/                       # 配置
│   ├── *.example.toml             # 模板（提交 GitHub）
│   ├── agent-templates/           # Agent 人格定义
│   └── plans/                     # 可执行的任务计划
├── scripts/                       # 运维脚本
│   ├── run_everos.py              # EverOS 启动入口（含 MCP 兼容层）
│   └── import_*.py                # 种子数据批量导入
├── rome →                         # 软链：GPU 推理优化调研（只读）
└── crucible →                     # 软链：K8s 集测框架（只读）
```

## 快速开始

```bash
# 1. 配置
cp configs/agent.example.toml configs/agent.toml
# → 编辑 agent.toml 填入本地路径

# 2. 启动 EverOS
source .venv/bin/activate
python scripts/run_everos.py server start

# 3. 验证
curl http://127.0.0.1:8000/health  # → {"status":"ok"}

# 4. 运行 Raven Agent（需要先配置 raven onboard）
export EVEROS_LLM__API_KEY="sk-xxx"
export EVEROS_EMBEDDING__API_KEY="sk-xxx"
raven agent -m "分析 rome/rubicon/data/results/ 下的实验结果"
```

## 参考

- [ROADMAP](docs/ROADMAP.md) — 当前进度和下一步
- [记忆系统概念设计](docs/memory-taxonomy.md) — EverOS 三层记忆详解
- [检查点执行协议](docs/checkpoint-protocol.md) — Plan → Execute → Verify 全流程
- Mindverse Macaron-V1-Preview / Mixture-of-LoRA
- EverMind 生态：EverOS / Raven / EverAlgo / EverMe
- EvoAgentBench (arXiv:2607.05202)

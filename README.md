# Noctua

基于 **EverMind 记忆演进 + 开源 LoRA 参数演练** 的自演进 Agent 系统。
演进同时发生在 prompt 层（记忆检索 + 技能复用）和参数层（LoRA 微调 + 路由激活）。

## 架构

```
Layer 1: 参数层演进 (Mindverse 路线)
  基座模型 ← Mixture-of-LoRA 技能包
  └─ verl-mint / AReaL-MinT RL 训练

Layer 2: 记忆层演进 (EverMind 路线)
  Agent 轨迹 → EverOS (episode/case/skill) → Reflection 离线进化

Layer 3: Agent Harness (Raven)
  Spine + SkillForge + Sentinel + Agent Templates
```

## 目录

```
noctua/
├── docs/              # 设计文档 & 路线图
│   ├── ROADMAP.md          # 六阶段路线图
│   ├── design.md           # 系统设计
│   ├── memory-taxonomy.md  # 记忆系统概念设计
│   └── architecture-memory.md  # 存储架构
├── scripts/           # 工具脚本
│   ├── run_everos.py        # EverOS 启动入口
│   └── gateway_compat.py   # EverMe MCP 兼容层
├── rome →             # 软链：GPU 推理优化调研 (只读)
├── crucible →         # 软链：K8s 集测框架 (只读)
└── pyproject.toml     # Python 项目配置 (uv)
```

## 快速开始

```bash
# 1. 启动 EverOS 记忆服务
cd noctua
source .venv/bin/activate
python -m everos.entrypoints.cli.main server start

# 2. 检查服务
curl http://127.0.0.1:8000/health
```

## 参考

- [ROADMAP](docs/ROADMAP.md)
- [记忆系统概念设计](docs/memory-taxonomy.md)
- [存储架构](docs/architecture-memory.md)
- Mindverse Macaron-V1-Preview / Mixture-of-LoRA
- EverMind 生态：EverOS / Raven / EverAlgo / EverMe
- EvoAgentBench (arXiv:2607.05202)

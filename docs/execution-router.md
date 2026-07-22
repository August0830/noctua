# 执行载体路由决策

> OpenCode 和 Raven 通过 EverOS 共享记忆，按任务确定性选择执行载体。
> 核心原则：**确定性的给 Raven 自动推进，不确定的给 OpenCode 探索排查。确定性可以积累。**

---

## 决策树

```
新任务 ──▶ mem_search("similar tasks") ──▶ 以前做过相似的吗？
                                                │
               ┌────────────────────────────────┴────────────────────────────┐
               ▼                                                              ▼
          有成熟的 Skill/Case                                          第一次遇到
               │                                                              │
               ▼                                                              ▼
        能否拆成确定性步骤？                                            需要探索 / 排查吗？
               │                                                              │
     ┌─────────┴─────────┐                                          ┌─────────┴─────────┐
     ▼                   ▼                                          ▼                   ▼
  全部确定           部分不确定                                  探索理解型           调试排查型
  (已知SOP)         (有模糊点)                               (搜索/阅读/设计)    (看日志/改代码/试错)
     │                   │                                          │                   │
     ▼                   ▼                                          ▼                   ▼
   Raven              OpenCode → Plan → Raven                  OpenCode              OpenCode
  (自动执行)        (先排查模糊点，产出Plan后Raven执行)       (知识探索)          (交互式排查)
```

---

## 分界线：任务确定性

| | Raven | OpenCode |
|---|---|---|
| **适合** | 已知怎么做，需要重复做 | 不知道怎么做，需要探索/排查 |
| **输入** | Plan YAML，步骤明确 | 自然语言描述，目标模糊 |
| **执行模式** | 自动推进，检查点暂停等人批 | 交互式，随时纠正方向 |
| **回退机制** | 失败后记录 case，靠后续反馈改进 | 人类在现场，边看边调 |
| **安全** | 检查点处的 human-in-loop | 全程 human-in-loop |
| **典型时长** | 分钟级 | 分钟到小时级 |
| **重复执行** | 每次一致，可 Scale | 每次不同，难以复制 |

---

## 任务生命周期：从 OpenCode 到 Raven

```
Phase A: 首次面对 ── OpenCode
  ├── 理解问题 → 尝试方案 → 失败 → 修复 → 成功
  ├── 过程记录为 episode + case (EverOS)
  └── 提炼为 Skill（"Caesar 环境搭建 SOP"）

Phase B: 第二次遇到 ── OpenCode 设计 Plan
  ├── mem_search("caesar env setup") → 召回上次经验
  ├── 基于上次经验，快速写出 Plan YAML
  └── Plan 中标出检查点（高风险步骤，必需人工确认）

Phase C: 第三次及以后 ── Raven 执行 Plan
  ├── 确定性步骤自动推进
  ├── 检查点暂停等人类确认
  └── 如果中途失败了 → 切回 OpenCode 排查

Phase D: 多次成功验证后
  ├── Skill → LoRA 训练数据 → 训进参数
  ├── 检查点可降级（required → optional → skip）
  └── 进一步靠近全自动
```

**关键：确定性可以积累。** 今天用 OpenCode 排查出来的经验，提炼成 Skill + LoRA，明天 Raven 就能自动执行。

---

## 具体场景对照

| 场景 | 载体 | 原因 |
|------|------|------|
| 跑已有 Crucible scaling 集测 | Raven | 步骤已知，63 个 case 已调通 |
| 新写 Caesar RayCluster test case | OpenCode → Plan → Raven | 先探索设计，产出 Plan 后 Raven 执行 |
| Rome H20 标准 batch 扫参 | Raven | 参数组合确定，纯执行 |
| Rome 奇怪 OOM 排查 | OpenCode | 根因未知，需要交互式查日志、改配置 |
| 设计 Noctua 新功能 | OpenCode | 创造性工作，无确定路径 |
| 每周运行 ROADMAP 进度检查 | Raven (Sentinel) | 重复定时任务 |
| 集成测试失败后 debug | OpenCode | 需要看日志、改代码、试错 |
| 导入种子数据 | Raven | `python scripts/import_*.py` 确定执行 |
| 新领域 onboarding | OpenCode → Plan → Raven | 先设计 onboarding YAML，后自动化 |
| 代码 MR 审查 | OpenCode | 需要理解语义、评估影响面 |

---

## 切换规则

```
Raven → OpenCode 切换（需人工介入）:
  ├── Raven 连续失败 2 次同一步骤
  ├── 检查点处人类选择 reject
  ├── 出现未预料的错误类型（不在已知 failure pattern 中）
  └── 需要修改代码而非修改参数

OpenCode → Raven 切换（可自动化）:
  ├── Plan YAML 已产出且经过人类确认
  ├── 排查完成，找到了确定性修复路径
  └── 任务可完全拆解为已知工具的调用序列
```

---

## 渐进自动化：检查点降级策略

初始 Plan 中所有检查点都是 `required`，随着 Skill 成熟逐步降级：

```
Skill 成功率 < 60%:   所有检查点 approval: required
Skill 成功率 60-80%:  非高危检查点降为 approval: optional
Skill 成功率 80-95%:  非高危检查点降为 approval: skip
Skill 成功率 > 95%:   仅保留高危检查点（生产变更、环境销毁等）
```

每个 Skill 的 `success_rate` 由 VerifierActor 持续追踪，自动触发降级建议。

---

## EverOS 桥接：两端无差别

无论 OpenCode 还是 Raven，产出都进同一个 EverOS：

```
OpenCode 产出:
  ├── 排查过程 → episode
  ├── 解决方案 → case
  └── 新 Plan → knowledge / skill reference

Raven 产出:
  ├── 执行轨迹 → case
  ├── 成功模式 → skill 候选（SkillForge）
  └── 失败报告 → episode（等待排查）

下次，无论是 OpenCode 还是 Raven 再遇相似问题 → mem_search 直接召回。
```

---

## 参考

- 设计文档：`docs/design.md` §3 人-Agent 协同工作流
- 检查点协议：`docs/checkpoint-protocol.md`
- 记忆分类法：`docs/memory-taxonomy.md`
- 路线图：`docs/ROADMAP.md`

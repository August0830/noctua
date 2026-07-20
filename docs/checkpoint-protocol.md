# Checkpoint Execution Protocol

> 人类和 Agent 之间的协作契约。Plan 驱动执行，检查点嵌入决策。

## 概念模型

```
Plan (一份任务计划)
 ├── meta: 任务元数据（领域、Agent、目标）
 ├── steps: 有序步骤列表
 │    ├── auto step: Agent 自动执行
 │    └── checkpoint: 暂停等人批准
 ├── context: 从 EverOS 加载的上下文引用
 └── trace: 运行时写入的决策追溯
```

## YAML Schema

### Plan 文件结构

```yaml
# plan: <plan_id>.yaml
# 存储在 configs/plans/ 目录

plan_id: "rome-h20-optimize-20260720"
domain: rome                   # crucible | rome
agent_template: rome            # 对应 configs/agent-templates/<name>/
status: draft                   # draft | running | paused | done | aborted
created_by: human               # human | agent
created_at: "2026-07-20T10:00:00Z"

context:                        # 从 EverOS 预加载的参考
  episodes:                     # 相关历史 episode
    - "seed-todos-ROADMAP"
  agent_cases:                  # 相关历史 case
    - "h20-batch-optimize-20260715"
  knowledge_docs:               # 相关设计文档
    - "inference-roofline-flowchart"
    - "optimization-playbook"
  skills:                       # 已有技能
    - "h20-batch-tuning"

steps:
  - id: "collect-baseline"
    description: "采集 H20 集群上 Qwen3-8B 的基线指标"
    type: auto                  # auto | checkpoint
    tool: read_metrics
    params:
      cluster: "h20-test"
      model: "Qwen3-8B"
      metrics: ["tokens_per_second", "gpu_utilization", "p50_latency"]
    expected_output: "baseline_metrics.json"

  - id: "review-baseline"
    description: "检查基线数据是否合理，确认优化方向"
    type: checkpoint
    checkpoint:
      approval: required        # required | optional | skip
      prompt: "基线数据: tokens/s=${step.collect-baseline.output.tokens_per_second}，GPU利用率=${step.collect-baseline.output.gpu_utilization}。确认继续优化？"
      timeout_minutes: 30       # 超时后自动跳过
    actions:                    # 人类可选操作
      - approve                 # 批准，继续下一步
      - modify                  # 修改参数后继续
      - reject                  # 拒绝，终止 plan
      - skip                    # 跳过此检查点

  - id: "design-experiment"
    description: "基于 Roofline 设计单变量扫描实验"
    type: auto
    tool: design_experiment
    params:
      baseline: "${step.collect-baseline.output}"
      roofline_data: "${context.knowledge_docs.inference-roofline-flowchart}"
      knobs: ["batch_size", "max_tokens"]
    expected_output: "experiment_plan.yaml"

  - id: "approve-experiment"
    description: "确认实验方案后提交 RayJob"
    type: checkpoint
    checkpoint:
      approval: required
      prompt: "实验方案: batch_size∈[4,8,16,32]，max_tokens∈[1024,2048,4096]。预计耗时 30 分钟。确认执行？"
    actions: [approve, modify, reject]

  - id: "run-experiment"
    description: "提交 RayJob 并监控进度"
    type: auto                # context_sensitive: auto 在当前环境，但如果提交到生产则需要嵌套 checkpoint
    tool: submit_rayjob
    params:
      experiment_plan: "${step.design-experiment.output}"
      cluster: "h20-test"
    expected_output: "experiment_results.json"

  - id: "report-findings"
    description: "分析结果并生成优化报告"
    type: auto
    tool: generate_report
    params:
      baseline: "${step.collect-baseline.output}"
      results: "${step.run-experiment.output}"
    expected_output: "optimization_report.md"

  - id: "production-decision"
    description: "决定是否将优化应用于生产"
    type: checkpoint
    checkpoint:
      approval: required       # 高危操作，必须批准
      prompt: "优化结果: 吞吐 ↑ ${step.report-findings.output.delta}%。建议在生产集群 H20-prod 上线。确认？"
      timeout_minutes: 60
    actions: [approve, reject, modify]
```

### 变量引用语法

步骤间通过 `${step.<step_id>.output.<field>}` 传递数据，引擎运行时解析。

### 检查点操作定义

| 操作 | Agent 行为 | 训练信号 |
|------|-----------|---------|
| `approve` | 继续下一步 | 正样本（approved decision → 后续 LoRA 训练正例） |
| `modify` + 新参数 | 用新参数重新执行当前步 | DPO pair（原始 vs 修改后） |
| `reject` + 理由 | 终止 plan，记录拒绝原因 | 负样本（bad decision → 避免重复） |
| `skip` | 跳过检查点，继续 | 弱正样本（人类认同无需审查） |

## 运行时状态机

```
          ┌─────────┐
          │  draft   │ ← 新建 plan
          └────┬─────┘
               │ start
               ▼
          ┌─────────┐
    ┌─────│ running  │──────┐
    │     └────┬─────┘      │
    │          │             │
    │    auto step 完成      │
    │          │             │
    │          ▼             │
    │     ┌──────────┐       │
    │     │  paused   │ ← 检查点触发   │
    │     └────┬─────┘       │
    │          │             │
    │    人类 approve/modify │  人类 reject
    │          │             │
    │          ▼             ▼
    │     back to       ┌─────────┐
    │     running       │ aborted │
    │                   └─────────┘
    │  所有步骤完成
    │          │
    │          ▼
    │     ┌─────────┐
    └────▶│  done    │
          └─────────┘
```

## 决策追溯链 (Trace)

每个步骤执行后记录：

```yaml
# 运行时 appending 到 plan.trace[]
trace:
  - step_id: "collect-baseline"
    status: completed
    started_at: "2026-07-20T10:01:00Z"
    finished_at: "2026-07-20T10:03:15Z"
    output_hash: "sha256:abc123"
    output_path: "data/baseline_metrics.json"

  - step_id: "review-baseline"
    status: approved
    decision:
      action: approve
      by: human                   # human | agent | auto
      at: "2026-07-20T10:04:30Z"
      comment: "基线正常，继续优化"

  - step_id: "design-experiment"
    status: completed
    started_at: "2026-07-20T10:04:31Z"
    finished_at: "2026-07-20T10:05:45Z"
    decision_rationale: |        # Agent 自述决策理由
      Roofline 显示 compute-bound，优先增大 batch_size。
      参照历史 case h20-batch-optimize-20260715，H20 显存上限的 80% 安全。

  - step_id: "run-experiment"
    status: completed
    started_at: "2026-07-20T10:06:00Z"
    finished_at: "2026-07-20T10:36:00Z"
    output_hash: "sha256:def456"

  - step_id: "report-findings"
    status: error
    error: "DeepSeek API timeout after 30s retry"
    retry_count: 3
```

## 集成到 Agent Template

Agent Template 中通过 `checkpoint_rules` 声明哪些操作触发检查点：

```yaml
# agent.md frontmatter 或独立 checkpoint_rules.yaml
checkpoint_rules:
  require_human_approval:
    - action: submit_rayjob
      when: target_cluster == "h20-prod"
    - action: modify_config
      when: scope == "production"
    - action: scale_cluster
    - action: trigger_lora_training
  
  optional_checkpoint:
    - action: submit_rayjob
      when: target_cluster == "h20-test"  # 测试集群可自动
    - action: generate_yaml               # YAML 生成后可选审查
  
  auto_approve:
    - action: read_metrics
    - action: read_file
    - action: analyze_data
```

## 阶段 3 对齐集成

每个检查点的决策自动成为训练信号：

```
approve → 正样本: {context, plan, decision="正确的下一个步骤"}
modify  → DPO pair: {context, plan, chosen=人类修改版, rejected=Agent原版}
reject  → 负样本: {context, plan, decision="不应执行的操作", reason=人类填写的原因}
```

## 与 ROADMAP 依赖关系

```
2.3 检查点协议 (本文件)
  ├── 被 2.4 决策追溯使用
  ├── 被 2.5 中断/恢复使用
  ├── 被 3.2 人类操作捕获使用
  └── 被 3.3 操作→训练数据转换使用
```

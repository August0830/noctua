"""Noctua 核心数据 Schema —— 记忆类型和训练数据的可序列化契约。

这些 Schema 定义了两条数据流的格式：
1. 向上流（Memory）：Episodic → Case → Skill，通过 EverOS 持久化
2. 向下流（Training）：Case → TrainingSample，喂入 verl-mint LoRA 训练

每一条 Schema 都是 Pydantic BaseModel：类型安全 + JSON 序列化 + 校验。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════
# 记忆类型 Schema
# ═══════════════════════════════════════════════════════════════════════


class MemorySource(str, Enum):
    """记忆来源标识——谁产生了这条记忆。"""
    human = "human"            # 人类直接产生的（对话、决策）
    agent = "agent"            # Agent 自主产生的（执行轨迹）


class AgentCaseStep(BaseModel):
    """Agent 执行轨迹中的一个步骤。"""
    turn: int
    action: str                               # 工具名 或 "respond"
    action_type: str                          # "tool_call" | "text_output" | "decision"
    reasoning: str = ""                       # Agent 的自述理由（如果提供）
    tool_args: dict[str, Any] | None = None   # 工具调用参数
    tool_result: Any = None                   # 工具返回结果
    success: bool | None = None               # None=未完成
    duration_ms: int | None = None            # 该步骤耗时
    error: str | None = None                  # 失败原因


class ProvenanceRef(BaseModel):
    """决策来源追溯——这个动作是受什么影响的。"""
    source_type: str                          # "lora" | "skill" | "episode" | "agent_case" | "knowledge_doc" | "base_model" | "human_override"
    source_id: str                            # LoRA 模块名 / skill id / episode id 等
    confidence: float = 1.0
    snippet: str = ""                         # 来源中的相关片段


class AgentCase(BaseModel):
    """Agent 执行一次完整任务的轨迹记录。

    EverOS 类型: agent_case
    用途: 成功的 → 提炼 Skill；失败 + 人类修正的 → LoRA 训练数据
    """
    case_id: str
    plan_id: str | None = None
    domain: str                               # "crucible" | "rome" | "paper-reading" | ...
    task_description: str                     # 人类可读的任务描述
    task_instruction: str = ""                # 给 Agent 的原始指令

    steps: list[AgentCaseStep] = Field(default_factory=list)
    provenance: list[ProvenanceRef] = Field(default_factory=list)

    # 结果
    success: bool
    artifact_paths: list[str] = Field(default_factory=list)  # 产出的文件路径
    summary: str = ""                         # Agent 自己写的结果摘要

    # 成本
    total_tokens: int = 0
    total_wall_time_seconds: float = 0.0
    total_turns: int = 0

    # 时间
    started_at: str = ""
    finished_at: str = ""

    # 质量
    verifier_score: float | None = None       # VerifierActor 评分 (0-1)
    human_decision: str | None = None         # "approve" | "modify" | "reject" | None(未审查)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def success_rate(self) -> float:
        if not self.steps:
            return 0.0
        done = [s for s in self.steps if s.success is not None]
        if not done:
            return 0.0
        return sum(1 for s in done if s.success) / len(done)

    @property
    def lora_contributions(self) -> list[str]:
        return [p.source_id for p in self.provenance if p.source_type == "lora"]

    @property
    def skill_contributions(self) -> list[str]:
        return [p.source_id for p in self.provenance if p.source_type == "skill"]


class SkillApplicability(BaseModel):
    """技能适用范围——对应 EvoAgentBench 警告二：每个技能必须声明适用边界。"""
    domains: list[str] = Field(default_factory=list)         # 适用领域
    conditions: list[str] = Field(default_factory=list)       # 前置条件（自然语言）
    exclusion_patterns: list[str] = Field(default_factory=list) # 不应使用的情况


class Skill(BaseModel):
    """从多个成功 Case 提炼的可复用执行流程。

    EverOS 类型: agent_skill
    关键设计: 适用范围声明 + 来源可追溯 + 信心评分
    """
    skill_id: str
    title: str
    description: str = ""

    # 来自哪些 case
    source_cases: list[str] = Field(default_factory=list)

    # 适用范围（EvoAgentBench 警告二）
    applicability: SkillApplicability = Field(default_factory=SkillApplicability)

    # 执行步骤
    prerequisites: list[str] = Field(default_factory=list)   # 前置条件
    steps: list[str] = Field(default_factory=list)            # 步骤说明

    # 质量
    success_rate: float = 0.0                                 # 源 case 的成功率
    confidence: float = 1.0                                   # SkillForge 信心评分

    # 版本
    version: str = "0.1.0"
    created_at: str = ""
    updated_at: str = ""


# ═══════════════════════════════════════════════════════════════════════
# 训练数据 Schema
# ═══════════════════════════════════════════════════════════════════════


class TrainingMessage(BaseModel):
    """一条对话消息——OpenAI 兼容格式，直接可用于 SFT/LoRA 训练。"""
    role: str                                 # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None   # assistant 消息中的 tool call
    tool_call_id: str | None = None                   # tool 消息中的 call id
    name: str | None = None                           # tool 消息中的函数名


class TrainingSample(BaseModel):
    """一条 LoRA 训练样本。

    格式兼容 OpenAI fine-tuning / verl-mint / HuggingFace SFT。
    包含完整的对话上下文 + 质量元数据，用于后续筛选和加权。
    """
    sample_id: str
    source_case_id: str
    domain: str

    # 训练对话
    messages: list[TrainingMessage] = Field(default_factory=list)

    # 质量标注
    quality_score: float                       # VerifierActor 评分 (0-1)
    success: bool
    human_verified: bool = False               # 是否经过人类确认

    # 技能归属（用于 Mixture-of-LoRA 的分模块训练）
    skill_ids: list[str] = Field(default_factory=list)

    # 训练信号类型（用于加权 / 筛选）
    signal_type: str = "positive"              # "positive" | "dpo_chosen" | "dpo_rejected" | "negative"

    # 元数据
    created_at: str = ""
    tags: list[str] = Field(default_factory=list)


class TrainingDataset(BaseModel):
    """一批 TrainingSample 的集合，可直接导出为 JSONL。

    JSONL 格式：每行一个 TrainingSample.model_dump_json()
    兼容 verl-mint 的 --data 参数。
    """
    dataset_id: str
    description: str = ""
    domain: str
    samples: list[TrainingSample] = Field(default_factory=list)
    created_at: str = ""

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def positive_count(self) -> int:
        return sum(1 for s in self.samples if s.signal_type == "positive")

    @property
    def dpo_count(self) -> int:
        return sum(1 for s in self.samples if s.signal_type in ("dpo_chosen", "dpo_rejected"))

    @property
    def quality_distribution(self) -> dict[str, int]:
        """按质量分桶统计。"""
        buckets = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for s in self.samples:
            q = s.quality_score
            if q < 0.3: buckets["0.0-0.3"] += 1
            elif q < 0.6: buckets["0.3-0.6"] += 1
            elif q < 0.8: buckets["0.6-0.8"] += 1
            else: buckets["0.8-1.0"] += 1
        return buckets

    def to_jsonl(self) -> str:
        """导出为 JSONL 字符串（每行一个样本）。"""
        return "\n".join(s.model_dump_json() for s in self.samples)

"""Checkpoint execution protocol — Python types and validation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
    draft = "draft"
    running = "running"
    paused = "paused"
    done = "done"
    aborted = "aborted"


class StepType(str, Enum):
    auto = "auto"
    checkpoint = "checkpoint"


class CheckpointAction(str, Enum):
    approve = "approve"
    modify = "modify"
    reject = "reject"
    skip = "skip"


class CheckpointApproval(str, Enum):
    required = "required"
    optional = "optional"
    skip = "skip"


# ── Plan model ────────────────────────────────────────────────────────


class CheckpointConfig(BaseModel):
    approval: CheckpointApproval = CheckpointApproval.required
    prompt: str = ""
    timeout_minutes: int = 30
    actions: list[CheckpointAction] = [
        CheckpointAction.approve,
        CheckpointAction.modify,
        CheckpointAction.reject,
    ]


class StepParams(BaseModel):
    model_config = {"extra": "allow"}


class Step(BaseModel):
    id: str
    description: str = ""
    type: StepType = StepType.auto
    tool: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    expected_output: str | None = None
    checkpoint: CheckpointConfig | None = None
    depends_on: list[str] = Field(default_factory=list)  # step ids that must complete first


class PlanContext(BaseModel):
    episodes: list[str] = Field(default_factory=list)
    agent_cases: list[str] = Field(default_factory=list)
    knowledge_docs: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    plan_id: str
    domain: str  # "crucible" | "rome"
    agent_template: str
    status: PlanStatus = PlanStatus.draft
    created_by: str = "human"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    context: PlanContext = Field(default_factory=PlanContext)
    steps: list[Step] = Field(default_factory=list)

    def checkpoints(self) -> list[Step]:
        return [s for s in self.steps if s.type == StepType.checkpoint]

    def next_step(self) -> Step | None:
        """Return the first step not yet completed."""
        # Steps are already ordered; find first non-done step
        # The trace tracks completion status at runtime
        return self.steps[0] if self.steps else None


# ── Trace model (runtime) ─────────────────────────────────────────────


class Decision(BaseModel):
    action: CheckpointAction
    by: str = "human"  # "human" | "agent" | "auto"
    at: datetime = Field(default_factory=datetime.utcnow)
    comment: str = ""
    modified_params: dict[str, Any] | None = None


class TraceEntry(BaseModel):
    step_id: str
    status: str  # "completed" | "approved" | "rejected" | "error" | "skipped"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_hash: str | None = None
    output_path: str | None = None
    decision: Decision | None = None
    decision_rationale: str | None = None
    error: str | None = None
    retry_count: int = 0


# ── Training signal (Phase 3) ─────────────────────────────────────────


class TrainingSignal(BaseModel):
    """A checkpoint decision converted to training data."""
    signal_type: str  # "positive" | "dpo_pair" | "negative"
    plan_id: str
    step_id: str
    context: PlanContext
    decision: Decision
    # For DPO pairs:
    agent_original: dict[str, Any] | None = None  # what agent proposed
    human_modified: dict[str, Any] | None = None  # what human changed it to
    # For negative:
    rejection_reason: str | None = None


class CheckpointRules(BaseModel):
    """Integrated with Agent Template to declare which actions need checkpoints."""
    require_human_approval: list[dict[str, Any]] = Field(default_factory=list)
    optional_checkpoint: list[dict[str, Any]] = Field(default_factory=list)
    auto_approve: list[dict[str, Any]] = Field(default_factory=list)

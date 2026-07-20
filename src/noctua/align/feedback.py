"""Human feedback capture + training signal conversion.

Phase 3.2 — Capture human actions at checkpoints: approve / modify / reject / reason.
Phase 3.3 — Convert human feedback into structured training signals for Phase 4 LoRA.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from noctua.agent.protocol import CheckpointAction, Decision, PlanContext


# ── Feedback capture ───────────────────────────────────────────────────


class HumanFeedback(BaseModel):
    """A single human decision captured at a checkpoint."""
    feedback_id: str
    plan_id: str
    step_id: str
    checkpoint_prompt: str                 # what the agent asked the human
    agent_proposal: dict[str, Any] | None = None  # what the agent proposed (before human review)

    decision: CheckpointAction             # approve / modify / reject / skip
    modified_params: dict[str, Any] | None = None  # if modify: new params
    reason: str = ""                       # why the human made this decision
    comment: str = ""                      # additional notes

    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    captured_by: str = "human"

    # Optional: link to the agent's own quality self-assessment
    agent_verdict_score: float | None = None


class FeedbackSession(BaseModel):
    """All feedback from one plan execution."""
    session_id: str
    plan_id: str
    agent_template: str | None = None
    domain: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    feedback_items: list[HumanFeedback] = Field(default_factory=list)

    def add_feedback(self, fb: HumanFeedback) -> None:
        self.feedback_items.append(fb)

    @property
    def acceptance_rate(self) -> float:
        """Human approval rate (approve + skip) / total."""
        if not self.feedback_items:
            return 1.0
        accepted = sum(
            1 for f in self.feedback_items
            if f.decision in (CheckpointAction.approve, CheckpointAction.skip)
        )
        return accepted / len(self.feedback_items)

    @property
    def rejection_rate(self) -> float:
        """Human rejection rate."""
        if not self.feedback_items:
            return 0.0
        return sum(1 for f in self.feedback_items if f.decision == CheckpointAction.reject) / len(self.feedback_items)

    @property
    def modification_rate(self) -> float:
        """Human modification rate (agent was close but not right)."""
        if not self.feedback_items:
            return 0.0
        return sum(1 for f in self.feedback_items if f.decision == CheckpointAction.modify) / len(self.feedback_items)


# ── Training signal conversion ─────────────────────────────────────────


class SignalType(str, Enum):
    positive = "positive"        # agent was right → reinforce
    dpo_pair = "dpo_pair"        # agent was close but human modified → learn preference
    negative = "negative"        # agent was wrong → avoid repeating


class TrainingSignal(BaseModel):
    """One training sample generated from human feedback."""
    signal_id: str
    signal_type: SignalType
    plan_id: str
    step_id: str

    # Context: what the agent saw before making its decision
    context: dict[str, Any] = Field(default_factory=dict)

    # For positive signals: agent's output was correct
    agent_correct_output: dict[str, Any] | None = None

    # For DPO pairs: agent proposed X, human modified to Y
    agent_proposal: dict[str, Any] | None = None
    human_preferred: dict[str, Any] | None = None

    # For negative signals: agent's output was wrong
    agent_wrong_output: dict[str, Any] | None = None
    rejection_reason: str | None = None

    # Metadata
    feedback_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    domain: str | None = None
    quality_score: float | None = None  # from VerifierActor


class TrainingSignalBatch(BaseModel):
    """A batch of training signals ready for LoRA training."""
    batch_id: str
    plan_id: str
    signals: list[TrainingSignal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def positive_count(self) -> int:
        return sum(1 for s in self.signals if s.signal_type == SignalType.positive)

    @property
    def dpo_count(self) -> int:
        return sum(1 for s in self.signals if s.signal_type == SignalType.dpo_pair)

    @property
    def negative_count(self) -> int:
        return sum(1 for s in self.signals if s.signal_type == SignalType.negative)

    @property
    def total(self) -> int:
        return len(self.signals)


# ── Converter: feedback → training signals ─────────────────────────────


def feedback_to_signals(
    feedback_session: FeedbackSession,
    agent_trace: dict[str, Any] | None = None,
) -> TrainingSignalBatch:
    """Convert a session of human feedback into a training signal batch.

    Mapping:
      approve → positive signal (agent was right, reinforce)
      modify  → DPO pair signal (agent was close, learn preference)
      reject  → negative signal (agent was wrong, avoid)
      skip    → weak positive signal
    """
    signals = []
    ctx = agent_trace or {}

    for i, fb in enumerate(feedback_session.feedback_items):
        signal_id = f"{feedback_session.plan_id}-sig-{i:03d}"

        if fb.decision == CheckpointAction.approve:
            signals.append(TrainingSignal(
                signal_id=signal_id,
                signal_type=SignalType.positive,
                plan_id=fb.plan_id,
                step_id=fb.step_id,
                context=ctx,
                agent_correct_output=fb.agent_proposal,
                feedback_id=fb.feedback_id,
                domain=feedback_session.domain,
                quality_score=fb.agent_verdict_score,
            ))

        elif fb.decision == CheckpointAction.modify and fb.modified_params:
            signals.append(TrainingSignal(
                signal_id=signal_id,
                signal_type=SignalType.dpo_pair,
                plan_id=fb.plan_id,
                step_id=fb.step_id,
                context=ctx,
                agent_proposal=fb.agent_proposal,
                human_preferred=fb.modified_params,
                feedback_id=fb.feedback_id,
                domain=feedback_session.domain,
                quality_score=fb.agent_verdict_score,
            ))

        elif fb.decision == CheckpointAction.reject:
            signals.append(TrainingSignal(
                signal_id=signal_id,
                signal_type=SignalType.negative,
                plan_id=fb.plan_id,
                step_id=fb.step_id,
                context=ctx,
                agent_wrong_output=fb.agent_proposal,
                rejection_reason=fb.reason or fb.comment,
                feedback_id=fb.feedback_id,
                domain=feedback_session.domain,
                quality_score=fb.agent_verdict_score,
            ))

        elif fb.decision == CheckpointAction.skip:
            signals.append(TrainingSignal(
                signal_id=signal_id,
                signal_type=SignalType.positive,
                plan_id=fb.plan_id,
                step_id=fb.step_id,
                context=ctx,
                agent_correct_output=fb.agent_proposal,
                feedback_id=fb.feedback_id,
                domain=feedback_session.domain,
                quality_score=fb.agent_verdict_score or 0.8,  # skip = weak confidence
            ))

    return TrainingSignalBatch(
        batch_id=f"{feedback_session.plan_id}-batch",
        plan_id=feedback_session.plan_id,
        signals=signals,
    )


# ── Alignment scoring ──────────────────────────────────────────────────


class AlignmentScore(BaseModel):
    """Track alignment convergence over time.

    Higher acceptance rate + lower rejection rate = better alignment.
    DPO pairs indicate the agent is close but needs fine-tuning.
    """
    plan_id: str
    domain: str | None = None
    total_checkpoints: int = 0
    accepted: int = 0      # approve + skip
    modified: int = 0
    rejected: int = 0

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.total_checkpoints if self.total_checkpoints > 0 else 1.0

    @property
    def alignment_score(self) -> float:
        """Composite alignment score: penalize rejections, reward acceptances.
        
        Formula: (accepted + 0.5*modified) / total
        Modify is better than reject (agent was close), but worse than accept.
        """
        if self.total_checkpoints == 0:
            return 1.0
        return (self.accepted + 0.5 * self.modified) / self.total_checkpoints

    def update(self, feedback: HumanFeedback) -> None:
        self.total_checkpoints += 1
        if feedback.decision in (CheckpointAction.approve, CheckpointAction.skip):
            self.accepted += 1
        elif feedback.decision == CheckpointAction.modify:
            self.modified += 1
        elif feedback.decision == CheckpointAction.reject:
            self.rejected += 1

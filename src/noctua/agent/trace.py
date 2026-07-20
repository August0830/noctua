"""Decision provenance tracing — record what drove every agent action.

Each agent action is annotated with its PROVENANCE: which source (LoRA, skill,
retrieved episode, base model) contributed to the decision.

This enables:
  - Debugging: "why did the agent choose batch_size=16?"
  - Attribution: "which LoRA module caused this behavior?"
  - Training: "which sources correlate with successful outcomes?"
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProvenanceSource(str, Enum):
    """What kind of source drove this decision."""
    base_model = "base_model"       # LLM without any injected context
    loRA = "lora"                    # A LoRA adapter module
    skill = "skill"                  # A SkillForge skill
    episode = "episode"              # A recalled user episode
    agent_case = "agent_case"        # A recalled agent execution case
    knowledge_doc = "knowledge_doc"  # A recalled knowledge document
    human_override = "human_override"  # Human changed agent's decision at checkpoint
    tool_output = "tool_output"      # The output of a previous tool call
    checkpoint_rule = "checkpoint_rule"  # A policy rule forced the decision


class ProvenanceItem(BaseModel):
    """A single source that contributed to this action."""
    source_type: ProvenanceSource
    source_id: str                         # LoRA module name, skill id, episode id, etc.
    confidence: float = 1.0                # How strongly this source influenced (0-1)
    snippet: str = ""                      # Relevant excerpt from the source
    retrieval_score: float | None = None   # Retrieval similarity score, if applicable


class ActionTrace(BaseModel):
    """Provenance chain for a single agent action (tool call or text output)."""
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    action_id: str                         # Unique id for this action in the agent loop
    action_type: str                       # "tool_call" | "text_output" | "decision"
    action_name: str                       # Tool name, or "respond", or checkpoint action
    action_params: dict[str, Any] | None = None
    action_output: Any | None = None

    # What sources contributed to this action
    sources: list[ProvenanceItem] = Field(default_factory=list)

    # Which sources were retrieved but NOT used (helps debug retrieval quality)
    candidates_considered: int = 0
    candidates_discarded: int = 0

    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    duration_ms: int | None = None

    # Outcome
    success: bool | None = None            # None = pending, True/False after completion
    error: str | None = None

    def finish(self, success: bool = True, error: str | None = None) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.duration_ms = int(
            (self.finished_at - self.started_at).total_seconds() * 1000
        )
        self.success = success
        self.error = error


class SessionTrace(BaseModel):
    """All action traces for a single agent session / plan execution."""
    session_id: str
    plan_id: str | None = None            # If this session is executing a Plan
    agent_template: str | None = None
    domain: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actions: list[ActionTrace] = Field(default_factory=list)

    def add_action(self, action: ActionTrace) -> None:
        self.actions.append(action)

    @property
    def loRA_actions(self) -> list[ActionTrace]:
        """Actions where a LoRA contributed."""
        return [
            a for a in self.actions
            if any(s.source_type == ProvenanceSource.lora for s in a.sources)
        ]

    @property
    def human_overrides(self) -> list[ActionTrace]:
        """Actions where human changed the agent's decision."""
        return [
            a for a in self.actions
            if any(s.source_type == ProvenanceSource.human_override for s in a.sources)
        ]

    def provenance_summary(self) -> dict[str, int]:
        """Count actions by provenance source type."""
        counts: dict[str, int] = {}
        for action in self.actions:
            for source in action.sources:
                key = source.source_type.value
                counts[key] = counts.get(key, 0) + 1
        return counts


# ── Trace → EverOS conversion ─────────────────────────────────────────

def trace_to_agent_case(trace: SessionTrace) -> dict[str, Any]:
    """Convert a session trace into an EverOS agent_case for memory storage."""
    steps = []
    for a in trace.actions:
        steps.append({
            "action": a.action_name,
            "type": a.action_type,
            "sources": [s.source_type.value for s in a.sources],
            "success": a.success,
            "duration_ms": a.duration_ms,
        })

    return {
        "session_id": trace.session_id,
        "plan_id": trace.plan_id,
        "domain": trace.domain,
        "total_actions": len(trace.actions),
        "success_rate": (
            sum(1 for a in trace.actions if a.success) / len(trace.actions)
            if trace.actions else 0
        ),
        "provenance_summary": trace.provenance_summary(),
        "lora_contributions": len(trace.loRA_actions),
        "human_overrides": len(trace.human_overrides),
        "steps": steps,
    }


def trace_to_training_signals(
    trace: SessionTrace,
    outcome_success: bool,
) -> list[dict[str, Any]]:
    """Extract training signals from a completed session trace.

    Positive signals: actions where LoRA/skill contributed AND action succeeded.
    Negative signals: actions where LoRA/skill contributed AND action failed.
    Human override signals: actions where human changed the decision (DPO pair).
    """
    signals = []
    for action in trace.actions:
        if not action.success and action.sources:
            signals.append({
                "signal_type": "negative",
                "trace_id": action.trace_id,
                "action": action.action_name,
                "sources": [s.source_id for s in action.sources],
                "error": action.error,
            })
        elif action.success:
            lora_sources = [s for s in action.sources if s.source_type == ProvenanceSource.lora]
            skill_sources = [s for s in action.sources if s.source_type == ProvenanceSource.skill]
            if lora_sources or skill_sources:
                signals.append({
                    "signal_type": "positive",
                    "trace_id": action.trace_id,
                    "action": action.action_name,
                    "lora_contributors": [s.source_id for s in lora_sources],
                    "skill_contributors": [s.source_id for s in skill_sources],
                })

    return signals

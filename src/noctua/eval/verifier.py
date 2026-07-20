"""VerifierActor — quality scoring for agent outputs.

Adapted from rome/rubicon/docs/designs/ray-agentic-batch-inference.md.
Runs locally (no Ray cluster needed) using LLM-as-Judge pattern.
Scores agent outputs on: correctness, efficiency, factuality, usability.
Output feeds into Phase 4 LoRA training data selection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"  # output is wrong, unusable
    major = "major"        # significant flaw, fix needed
    minor = "minor"        # works but could be better
    info = "info"          # observation, no action needed


class VerdictIssue(BaseModel):
    step: int | None = None           # which step of the agent trajectory
    severity: Severity
    dimension: str                     # "correctness" | "efficiency" | "factuality" | "completeness"
    detail: str


class Verdict(BaseModel):
    """Structured quality verdict for an agent output."""
    quality_score: float = 0.0         # 0.0-1.0, overall quality
    usable_for_sft: bool = False       # can this output be used for SFT training?
    usable_for_rl: bool = True         # can this output be used for RL training?
    has_error_recovery: bool = False   # did the agent encounter and fix errors?
    issues: list[VerdictIssue] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)  # per-dimension scores
    summary: str = ""

    @property
    def is_perfect(self) -> bool:
        return self.quality_score >= 0.95 and not any(
            i.severity in (Severity.critical, Severity.major) for i in self.issues
        )

    @property
    def critical_issues(self) -> list[VerdictIssue]:
        return [i for i in self.issues if i.severity == Severity.critical]


# ── Verifier prompt templates ─────────────────────────────────────────

ROME_VERIFIER_PROMPT = """You are a GPU inference optimization reviewer auditing an Agent's analysis report.

Review the following output for:
1. **Correctness** — Are the metrics correct? Is the Roofline classification right?
2. **Efficiency** — Is the analysis concise? Any redundant calculations?
3. **Factuality** — Are all numbers traceable to raw experiment data? Any hallucinated claims?
4. **Completeness** — Does the analysis cover all required dimensions (L1/L2/L3)?

Agent Output:
{agent_output}

Context (experiment data referenced):
{context}

Output JSON:
{{
  "quality_score": 0.0-1.0,
  "usable_for_sft": true/false,
  "usable_for_rl": true/false,
  "has_error_recovery": true/false,
  "issues": [
    {{"step": null, "severity": "critical/major/minor/info", "dimension": "correctness/efficiency/factuality/completeness", "detail": "..."}}
  ],
  "dimensions": {{"correctness": 0.0-1.0, "efficiency": 0.0-1.0, "factuality": 0.0-1.0, "completeness": 0.0-1.0}},
  "summary": "one-line verdict"
}}"""


CRUCIBLE_VERIFIER_PROMPT = """You are a Kubernetes integration testing reviewer auditing an Agent's test case and execution report.

Review the following output for:
1. **Correctness** — Does the YAML follow Crucible conventions? Are assertions valid?
2. **Diagnostic quality** — Is the failure chain logical? Is root cause analysis evidence-based?
3. **Completeness** — Are all required sections present (Failure Chain, Root Cause, Confirmed Facts)?
4. **Safety** — Did the agent respect checkpoint rules? No unauthorized cluster changes?

Agent Output:
{agent_output}

Context (test case YAML + cluster state):
{context}

Output JSON:
{{
  "quality_score": 0.0-1.0,
  "usable_for_sft": true/false,
  "usable_for_rl": true/false,
  "has_error_recovery": true/false,
  "issues": [
    {{"step": null, "severity": "critical/major/minor/info", "dimension": "correctness/diagnostics/completeness/safety", "detail": "..."}}
  ],
  "dimensions": {{"correctness": 0.0-1.0, "diagnostics": 0.0-1.0, "completeness": 0.0-1.0, "safety": 0.0-1.0}},
  "summary": "one-line verdict"
}}"""


# ── Trajectory classification ─────────────────────────────────────────

class TrajectoryClass(str, Enum):
    """Classification of agent trajectory for training data selection.
    
    Based on Rome design: SFT = imitation learning (only correct trajectories),
    RL = can learn from both success and failure.
    """
    perfect = "perfect"              # answer correct + efficient → SFT ✅ RL ✅
    correct_inefficient = "correct_inefficient"  # correct but redundant → SFT ✅ RL ✅
    error_then_recovery = "error_then_recovery"  # error → fix → success → SFT ✅✅ RL ✅✅ (most valuable)
    answer_wrong = "answer_wrong"    # wrong output → SFT ❌ RL ✅
    format_error = "format_error"    # garbled output → SFT ❌ RL ❌ → discard


def classify_trajectory(verdict: Verdict, output_correct: bool) -> TrajectoryClass:
    """Classify a trajectory based on verdict + ground truth correctness."""
    if not output_correct and not verdict.has_error_recovery:
        return TrajectoryClass.answer_wrong
    if verdict.has_error_recovery and output_correct:
        return TrajectoryClass.error_then_recovery
    if verdict.is_perfect:
        return TrajectoryClass.perfect
    if output_correct and not verdict.is_perfect:
        return TrajectoryClass.correct_inefficient
    return TrajectoryClass.format_error


# ── Verifier execution ─────────────────────────────────────────────────

class VerifierConfig(BaseModel):
    domain: str = "rome"             # "rome" | "crucible"
    min_quality_for_sft: float = 0.7  # below this → not usable for SFT
    model: str = "deepseek-chat"     # LLM to use for verification
    temperature: float = 0.0         # deterministic verification


def build_verifier_prompt(domain: str, agent_output: str, context: str = "") -> str:
    prompt_template = ROME_VERIFIER_PROMPT if domain == "rome" else CRUCIBLE_VERIFIER_PROMPT
    return prompt_template.format(agent_output=agent_output, context=context)


def parse_verdict(raw_json: str) -> Verdict:
    """Parse LLM output into structured verdict."""
    import json as _json
    try:
        data = _json.loads(raw_json)
    except _json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        if "```json" in raw_json:
            block = raw_json.split("```json")[1].split("```")[0]
            data = _json.loads(block)
        elif "```" in raw_json:
            block = raw_json.split("```")[1].split("```")[0]
            data = _json.loads(block)
        else:
            return Verdict(quality_score=0.0, usable_for_sft=False, summary="parse error")

    return Verdict(
        quality_score=float(data.get("quality_score", 0)),
        usable_for_sft=bool(data.get("usable_for_sft", False)),
        usable_for_rl=bool(data.get("usable_for_rl", True)),
        has_error_recovery=bool(data.get("has_error_recovery", False)),
        issues=[VerdictIssue(**i) for i in data.get("issues", [])],
        dimensions=data.get("dimensions", {}),
        summary=str(data.get("summary", "")),
    )

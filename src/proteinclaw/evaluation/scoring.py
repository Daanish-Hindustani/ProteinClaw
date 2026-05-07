"""Evaluation domain types: per-metric Score, Verdict, Critique, Evaluation.

Two design decisions worth understanding:

1. Scores are **per-metric, never collapsed to a scalar.** This keeps the
   door open for Pareto-style optimization (multi-objective is native to
   protein design — pLDDT, RMSD, clash, novelty rarely move together).
2. Every Evaluation carries a textual `Critique`. Feedback Descent (Phase 7)
   consumes the critique as high-bandwidth signal; the scalar verdict alone
   would compress away the directional information.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.types import Metric


class MetricScore(BaseModel):
    """One metric's observed value plus its pass/fail decision.

    Attributes:
        metric: Which metric this score is for.
        value: Observed numeric value.
        passed: True iff a SuccessCriterion targeting this metric was satisfied.
            None when no criterion applies (the metric was reported anyway).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: Metric
    value: float
    passed: bool | None = None


class Score(BaseModel):
    """All metric scores for a single branch.

    Stored as a tuple to preserve immutability. Use `get(metric)` for
    lookup; iteration is direct.

    Attributes:
        branch_id: Branch this score belongs to.
        metric_scores: Per-metric values; order is not significant.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch_id: str
    metric_scores: tuple[MetricScore, ...] = ()

    def get(self, metric: Metric) -> float | None:
        """Return the observed value for `metric`, or None if not present."""
        for s in self.metric_scores:
            if s.metric == metric:
                return s.value
        return None

    @property
    def all_passed(self) -> bool:
        """True iff every MetricScore with a pass/fail decision passed."""
        decisions = [s.passed for s in self.metric_scores if s.passed is not None]
        return bool(decisions) and all(decisions)


class Verdict(StrEnum):
    """The Evaluator's recommendation to the Orchestrator."""

    STOP_SUCCESS = "stop_success"
    STOP_FAILURE = "stop_failure"
    RETRY = "retry"
    BRANCH = "branch"


class Critique(BaseModel):
    """Textual feedback on a branch — the signal Feedback Descent consumes.

    Kept structured (summary + weaknesses + suggestions) rather than free
    prose so the optimizer's editor LLM can reliably parse it.

    Attributes:
        branch_id: Branch this critique describes.
        summary: One-paragraph human-readable assessment.
        weaknesses: Specific issues identified (e.g. "high clash score in interface").
        suggestions: Concrete next steps (e.g. "try shorter contig at residue 42").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch_id: str
    summary: str
    weaknesses: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()


class Evaluation(BaseModel):
    """One evaluator output for one branch.

    Attributes:
        evaluation_id: Unique id; UUIDv4 by default.
        branch_id: Branch evaluated.
        task_id: Owning task.
        score: Per-metric scores.
        verdict: Recommendation to the orchestrator.
        critique: Textual feedback for the optimizer.
        evaluator_name: Identifier for the evaluator that produced this
            (useful when multiple evaluators are composed in Phase 3).
        timestamp: UTC time the evaluation was produced.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(default_factory=lambda: str(uuid4()))
    branch_id: str
    task_id: str
    score: Score
    verdict: Verdict
    critique: Critique
    evaluator_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

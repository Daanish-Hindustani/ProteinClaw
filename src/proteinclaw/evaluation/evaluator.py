"""Evaluator: composes metrics into Score, Verdict, and Critique.

The Evaluator's job per branch:

1. For every metric in the registry, attempt to extract a value from the
   branch payload (`metrics.compute`).
2. For every `SuccessCriterion` on the task, compare the observed value
   against its threshold and record pass/fail per metric.
3. Emit a `Score` (per-metric values + decisions), a `Verdict`
   (STOP_SUCCESS / RETRY / BRANCH / STOP_FAILURE), and a textual
   `Critique` summarising what passed, what failed, and what to try next.

Verdict policy (Phase 3, deterministic):

- All criteria pass → STOP_SUCCESS.
- 0 criteria → STOP_FAILURE (nothing to evaluate).
- pass_fraction >= retry_floor → RETRY (refine the same approach).
- pass_fraction <  retry_floor → BRANCH (different approach needed).

Thresholds are loaded from YAML — no magic numbers in code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.types import Comparison, Metric, passes
from proteinclaw.evaluation.metrics import EXTRACTORS, MetricExtractor, compute
from proteinclaw.evaluation.scoring import (
    Critique,
    Evaluation,
    MetricScore,
    Score,
    Verdict,
)
from proteinclaw.orchestrator.task import SuccessCriterion


class EvaluationConfig(BaseModel):
    """Loaded form of `config/evaluation.yaml`.

    Attributes:
        defaults: Map of metric → (threshold, comparison) used when a
            SuccessCriterion does not override.
        retry_floor: Pass-fraction at or above which the evaluator
            recommends RETRY rather than BRANCH.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    defaults: dict[Metric, tuple[float, Comparison]] = Field(default_factory=dict)
    retry_floor: float = Field(default=0.5, ge=0.0, le=1.0)

    @classmethod
    def from_yaml(cls, path: Path) -> EvaluationConfig:
        """Load and validate evaluator config from a YAML file."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults_raw: Mapping[str, Any] = raw.get("defaults", {})
        defaults: dict[Metric, tuple[float, Comparison]] = {}
        for name, body in defaults_raw.items():
            defaults[Metric(name)] = (
                float(body["threshold"]),
                Comparison(body["comparison"]),
            )
        verdict_raw = raw.get("verdict", {})
        return cls(
            defaults=defaults,
            retry_floor=float(verdict_raw.get("retry_floor", 0.5)),
        )


class Evaluator:
    """Stateless evaluator that consumes branch payloads and produces evaluations.

    Construct once per session with the loaded config and any metric-extractor
    overrides; call `evaluate()` per branch.
    """

    def __init__(
        self,
        *,
        name: str,
        config: EvaluationConfig,
        extractors: dict[Metric, MetricExtractor] | None = None,
    ) -> None:
        """Bind config and (optionally) override extractors.

        Args:
            name: Identifier surfaced in the `Evaluation.evaluator_name` field.
            config: Loaded `EvaluationConfig`.
            extractors: Optional override dict. Falls back to the module
                default `EXTRACTORS` when None.
        """
        self._name = name
        self._config = config
        self._extractors = extractors if extractors is not None else EXTRACTORS

    def evaluate(
        self,
        *,
        branch_id: str,
        task_id: str,
        criteria: tuple[SuccessCriterion, ...],
        payload: dict[str, Any],
    ) -> Evaluation:
        """Evaluate one branch payload against the task's success criteria.

        Args:
            branch_id: Branch this evaluation is for.
            task_id: Owning task.
            criteria: SuccessCriteria from the task.
            payload: Sub-agent's branch payload (tool outputs and any
                pre-computed metrics under `payload["metrics"]`).

        Returns:
            One `Evaluation` carrying Score, Verdict, and Critique.
        """
        decisions = self._decisions_by_metric(criteria, payload)
        metric_scores = self._build_metric_scores(payload, decisions)
        score = Score(branch_id=branch_id, metric_scores=metric_scores)
        verdict = self._verdict(criteria, decisions)
        critique = self._critique(branch_id, criteria, decisions, score, verdict)
        return Evaluation(
            branch_id=branch_id,
            task_id=task_id,
            score=score,
            verdict=verdict,
            critique=critique,
            evaluator_name=self._name,
        )

    def _decisions_by_metric(
        self,
        criteria: tuple[SuccessCriterion, ...],
        payload: dict[str, Any],
    ) -> dict[Metric, tuple[SuccessCriterion, float | None, bool | None]]:
        """For each criterion, record (criterion, observed_value, pass/fail)."""
        out: dict[Metric, tuple[SuccessCriterion, float | None, bool | None]] = {}
        for c in criteria:
            value = compute(c.metric, payload)
            decision = None if value is None else passes(value, c.threshold, c.comparison)
            out[c.metric] = (c, value, decision)
        return out

    def _build_metric_scores(
        self,
        payload: dict[str, Any],
        decisions: dict[Metric, tuple[SuccessCriterion, float | None, bool | None]],
    ) -> tuple[MetricScore, ...]:
        """Build MetricScore tuple for every metric we could extract.

        Includes both criterion-targeted metrics (with pass/fail) and any
        non-criterion metric the payload happens to report (no decision).
        """
        scores: list[MetricScore] = []
        seen: set[Metric] = set()
        for metric, (_, value, decision) in decisions.items():
            seen.add(metric)
            if value is None:
                continue
            scores.append(MetricScore(metric=metric, value=value, passed=decision))
        for metric, extractor in self._extractors.items():
            if metric in seen:
                continue
            value = extractor(payload)
            if value is None:
                continue
            scores.append(MetricScore(metric=metric, value=value, passed=None))
        return tuple(scores)

    def _verdict(
        self,
        criteria: tuple[SuccessCriterion, ...],
        decisions: dict[Metric, tuple[SuccessCriterion, float | None, bool | None]],
    ) -> Verdict:
        """Apply the verdict policy described in the module docstring."""
        if not criteria:
            return Verdict.STOP_FAILURE
        passed = sum(1 for _, _, d in decisions.values() if d is True)
        total = len(criteria)
        if passed == total:
            return Verdict.STOP_SUCCESS
        if passed / total >= self._config.retry_floor:
            return Verdict.RETRY
        return Verdict.BRANCH

    def _critique(
        self,
        branch_id: str,
        criteria: tuple[SuccessCriterion, ...],
        decisions: dict[Metric, tuple[SuccessCriterion, float | None, bool | None]],
        score: Score,
        verdict: Verdict,
    ) -> Critique:
        """Generate a deterministic textual critique.

        Phase 3 keeps this template-driven for predictability and cheap
        tests. Phase 7 may swap in an LLM-driven critique writer.
        """
        weaknesses: list[str] = []
        suggestions: list[str] = []
        for metric, (criterion, value, decision) in decisions.items():
            if decision is True:
                continue
            if value is None:
                weaknesses.append(f"{criterion.name}: {metric.value} not present in payload")
                suggestions.append(
                    f"ensure the sub-agent runs the tool that produces {metric.value}"
                )
                continue
            weaknesses.append(
                f"{criterion.name}: observed {metric.value}={value:.3f} "
                f"failed {criterion.comparison.value} {criterion.threshold:.3f}"
            )
            suggestions.append(
                f"target {metric.value} {criterion.comparison.value} {criterion.threshold:.3f} "
                f"(currently {value:.3f})"
            )
        summary = _summary_line(score, criteria, verdict)
        return Critique(
            branch_id=branch_id,
            summary=summary,
            weaknesses=tuple(weaknesses),
            suggestions=tuple(suggestions),
        )


def _summary_line(score: Score, criteria: tuple[SuccessCriterion, ...], verdict: Verdict) -> str:
    """Craft a one-line summary used as the head of every critique."""
    if not criteria:
        return "No success criteria provided; evaluator could not produce a decision."
    passed = sum(1 for s in score.metric_scores if s.passed is True)
    total = len(criteria)
    return f"Branch passed {passed}/{total} criteria; recommended next step: {verdict.value}."

"""Tests for evaluation/scoring.py — Score lookup, all_passed, round-trip, immutability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proteinclaw.common.types import Metric
from proteinclaw.evaluation.scoring import (
    Critique,
    Evaluation,
    MetricScore,
    Score,
    Verdict,
)


def test_score_get_returns_value_and_none() -> None:
    s = Score(
        branch_id="b1",
        metric_scores=(
            MetricScore(metric=Metric.PLDDT, value=0.85, passed=True),
            MetricScore(metric=Metric.RMSD, value=2.1, passed=False),
        ),
    )
    assert s.get(Metric.PLDDT) == 0.85
    assert s.get(Metric.RMSD) == 2.1
    assert s.get(Metric.NOVELTY) is None


def test_all_passed_true_when_all_decisions_pass() -> None:
    s = Score(
        branch_id="b1",
        metric_scores=(
            MetricScore(metric=Metric.PLDDT, value=0.9, passed=True),
            MetricScore(metric=Metric.PTM, value=0.8, passed=True),
        ),
    )
    assert s.all_passed is True


def test_all_passed_false_when_any_fails() -> None:
    s = Score(
        branch_id="b1",
        metric_scores=(
            MetricScore(metric=Metric.PLDDT, value=0.9, passed=True),
            MetricScore(metric=Metric.RMSD, value=5.0, passed=False),
        ),
    )
    assert s.all_passed is False


def test_all_passed_false_when_no_decisions() -> None:
    s = Score(
        branch_id="b1",
        metric_scores=(MetricScore(metric=Metric.NOVELTY, value=0.5),),
    )
    # No criterion → no decision → all_passed must be False (vacuously-true is dangerous here).
    assert s.all_passed is False


def test_metric_score_is_frozen() -> None:
    ms = MetricScore(metric=Metric.PLDDT, value=0.9, passed=True)
    with pytest.raises(ValidationError):
        ms.value = 0.1  # type: ignore[misc]


def test_evaluation_round_trip() -> None:
    e = Evaluation(
        branch_id="b1",
        task_id="t1",
        score=Score(
            branch_id="b1",
            metric_scores=(MetricScore(metric=Metric.PLDDT, value=0.9, passed=True),),
        ),
        verdict=Verdict.STOP_SUCCESS,
        critique=Critique(
            branch_id="b1",
            summary="Strong fold confidence and clean interface.",
            weaknesses=("clash_score borderline",),
            suggestions=("refine sidechain at residue 42",),
        ),
        evaluator_name="binder_evaluator_v1",
    )
    rt = Evaluation.model_validate_json(e.model_dump_json())
    assert rt == e


def test_critique_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        Critique(  # type: ignore[call-arg]
            branch_id="b1",
            summary="ok",
            unknown="field",
        )

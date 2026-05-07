"""Tests for evaluation/evaluator.py — verdict policy, critique generation, YAML config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from proteinclaw.common.types import Comparison, Metric
from proteinclaw.evaluation.evaluator import EvaluationConfig, Evaluator
from proteinclaw.evaluation.scoring import Verdict
from proteinclaw.orchestrator.task import SuccessCriterion


def _config() -> EvaluationConfig:
    return EvaluationConfig(defaults={}, retry_floor=0.5)


def _evaluator() -> Evaluator:
    return Evaluator(name="test", config=_config())


def _criterion(metric: Metric, threshold: float, comparison: Comparison) -> SuccessCriterion:
    return SuccessCriterion(
        name=f"{metric.value}_target",
        metric=metric,
        threshold=threshold,
        comparison=comparison,
    )


def _payload_with_fold(plddt: float, ptm: float) -> dict[str, Any]:
    return {"fold": {"plddt": plddt, "ptm": ptm}}


def test_all_pass_yields_stop_success() -> None:
    ev = _evaluator()
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(
            _criterion(Metric.PLDDT, 0.8, Comparison.GTE),
            _criterion(Metric.PTM, 0.7, Comparison.GTE),
        ),
        payload=_payload_with_fold(0.9, 0.85),
    )
    assert out.verdict == Verdict.STOP_SUCCESS
    assert out.score.all_passed is True
    assert "passed 2/2" in out.critique.summary


def test_partial_pass_above_floor_yields_retry() -> None:
    ev = _evaluator()
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(
            _criterion(Metric.PLDDT, 0.8, Comparison.GTE),
            _criterion(Metric.PTM, 0.7, Comparison.GTE),
        ),
        payload=_payload_with_fold(0.9, 0.5),  # plddt passes, ptm fails
    )
    assert out.verdict == Verdict.RETRY
    assert any("ptm_target" in w for w in out.critique.weaknesses)
    assert any("ptm" in s for s in out.critique.suggestions)


def test_partial_pass_below_floor_yields_branch() -> None:
    ev = Evaluator(name="t", config=EvaluationConfig(defaults={}, retry_floor=0.6))
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(
            _criterion(Metric.PLDDT, 0.8, Comparison.GTE),
            _criterion(Metric.PTM, 0.7, Comparison.GTE),
        ),
        payload=_payload_with_fold(0.9, 0.5),  # 1/2 = 0.5 < 0.6 floor
    )
    assert out.verdict == Verdict.BRANCH


def test_all_fail_yields_branch() -> None:
    ev = _evaluator()
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(_criterion(Metric.PLDDT, 0.8, Comparison.GTE),),
        payload=_payload_with_fold(0.5, 0.5),
    )
    assert out.verdict == Verdict.BRANCH


def test_no_criteria_yields_stop_failure() -> None:
    out = _evaluator().evaluate(branch_id="b1", task_id="t1", criteria=(), payload={})
    assert out.verdict == Verdict.STOP_FAILURE
    assert "No success criteria" in out.critique.summary


def test_missing_metric_in_payload_records_weakness_without_value() -> None:
    ev = _evaluator()
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(_criterion(Metric.PLDDT, 0.8, Comparison.GTE),),
        payload={},  # no fold output
    )
    assert out.verdict == Verdict.BRANCH
    assert any("not present in payload" in w for w in out.critique.weaknesses)
    assert all(s.passed is None for s in out.score.metric_scores)
    # No metric value for plddt should appear in score because extractor returned None.
    assert out.score.get(Metric.PLDDT) is None


def test_extra_non_criterion_metric_recorded_without_decision() -> None:
    ev = _evaluator()
    payload = {
        "fold": {"plddt": 0.9, "ptm": 0.7},
        "metrics": {"rmsd": 2.0},
    }
    out = ev.evaluate(
        branch_id="b1",
        task_id="t1",
        criteria=(_criterion(Metric.PLDDT, 0.8, Comparison.GTE),),
        payload=payload,
    )
    # plddt has a decision; ptm and rmsd are reported without one.
    decisions = {s.metric: s.passed for s in out.score.metric_scores}
    assert decisions[Metric.PLDDT] is True
    assert decisions[Metric.PTM] is None
    assert decisions[Metric.RMSD] is None


def test_evaluation_config_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "evaluation.yaml"
    yaml_path.write_text(
        "defaults:\n"
        "  plddt:\n"
        "    threshold: 0.8\n"
        "    comparison: gte\n"
        "  rmsd:\n"
        "    threshold: 3.0\n"
        "    comparison: lte\n"
        "verdict:\n"
        "  retry_floor: 0.6\n"
    )
    cfg = EvaluationConfig.from_yaml(yaml_path)
    assert cfg.defaults[Metric.PLDDT] == (0.8, Comparison.GTE)
    assert cfg.defaults[Metric.RMSD] == (3.0, Comparison.LTE)
    assert cfg.retry_floor == pytest.approx(0.6)


def test_evaluation_config_loads_repo_default(tmp_path: Path) -> None:
    """The repo-shipped config/evaluation.yaml must round-trip cleanly."""
    repo_path = Path(__file__).resolve().parents[2] / "config" / "evaluation.yaml"
    cfg = EvaluationConfig.from_yaml(repo_path)
    assert Metric.PLDDT in cfg.defaults
    assert 0.0 <= cfg.retry_floor <= 1.0

"""Tests for evaluation/metrics.py — extractors, dispatch, missing-data behavior."""

from __future__ import annotations

import pytest

from proteinclaw.common.types import Metric
from proteinclaw.evaluation.metrics import (
    EXTRACTORS,
    compute,
    extract_novelty,
    extract_passthrough,
    extract_plddt,
    extract_ptm,
)


def test_plddt_present() -> None:
    assert extract_plddt({"fold": {"plddt": 0.92}}) == pytest.approx(0.92)


def test_plddt_missing_returns_none() -> None:
    assert extract_plddt({}) is None
    assert extract_plddt({"fold": "not-a-dict"}) is None
    assert extract_plddt({"fold": {}}) is None
    assert extract_plddt({"fold": {"plddt": "high"}}) is None


def test_ptm_present_and_missing() -> None:
    assert extract_ptm({"fold": {"ptm": 0.81}}) == pytest.approx(0.81)
    assert extract_ptm({"fold": {}}) is None


def test_novelty_no_hits_is_fully_novel() -> None:
    assert extract_novelty({"foldseek": {"hits": []}}) == 1.0


def test_novelty_with_top_hit() -> None:
    out = extract_novelty({"foldseek": {"hits": [{"tm_score": 0.7}, {"tm_score": 0.3}]}})
    assert out == pytest.approx(0.30, abs=1e-9)


def test_novelty_clamped_at_zero() -> None:
    # tm_score > 1.0 would imply identical structure; clamp at 0 (no novelty).
    out = extract_novelty({"foldseek": {"hits": [{"tm_score": 1.2}]}})
    assert out == 0.0


def test_novelty_missing_returns_none() -> None:
    assert extract_novelty({}) is None
    assert extract_novelty({"foldseek": "not-a-dict"}) is None
    assert extract_novelty({"foldseek": {"hits": "not-a-list"}}) is None
    assert extract_novelty({"foldseek": {"hits": ["not-a-dict"]}}) is None
    assert extract_novelty({"foldseek": {"hits": [{}]}}) is None


def test_passthrough_reads_metrics_dict() -> None:
    extractor = extract_passthrough("rmsd")
    assert extractor({"metrics": {"rmsd": 1.7}}) == pytest.approx(1.7)
    assert extractor({}) is None
    assert extractor({"metrics": "not-a-dict"}) is None
    assert extractor({"metrics": {"rmsd": "not-a-number"}}) is None


def test_compute_dispatches_to_registry() -> None:
    payload = {"fold": {"plddt": 0.85, "ptm": 0.75}, "metrics": {"clash_score": 2.1}}
    assert compute(Metric.PLDDT, payload) == pytest.approx(0.85)
    assert compute(Metric.PTM, payload) == pytest.approx(0.75)
    assert compute(Metric.CLASH_SCORE, payload) == pytest.approx(2.1)


def test_extractors_cover_every_metric_enum_value() -> None:
    for metric in Metric:
        assert metric in EXTRACTORS

"""Tests for evaluation/metrics.py — extractors, dispatch, missing-data behavior."""

from __future__ import annotations

import pytest

from proteinclaw.common.types import Metric
from proteinclaw.evaluation.metrics import (
    EXTRACTORS,
    compute,
    extract_binder_monomer_confidence,
    extract_clash_score,
    extract_complex_confidence,
    extract_hotspot_satisfaction,
    extract_interface_contacts,
    extract_interface_sasa,
    extract_novelty,
    extract_passthrough,
    extract_plddt,
    extract_ptm,
    extract_target_binder_min_distance,
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


def _atom_line(
    serial: int,
    atom: str,
    chain: str,
    resseq: int,
    x: float,
    y: float,
    z: float,
    element: str,
) -> str:
    return (
        f"ATOM  {serial:>5d} {atom:^4s} ALA {chain}{resseq:>4d}    "
        f"{x:>8.3f}{y:>8.3f}{z:>8.3f}{1.0:>6.2f}{80.0:>6.2f}"
        f"          {element:>2s}"
    )


def test_real_binder_interface_metrics_from_complex_pdb(tmp_path) -> None:  # noqa: ANN001
    pdb = tmp_path / "complex.pdb"
    pdb.write_text(
        "\n".join(
            [
                _atom_line(1, "CA", "A", 10, 0.0, 0.0, 0.0, "C"),
                _atom_line(2, "CB", "A", 10, 0.0, 1.0, 0.0, "C"),
                _atom_line(3, "CA", "B", 1, 3.0, 0.0, 0.0, "C"),
                _atom_line(4, "CB", "B", 1, 1.5, 0.0, 0.0, "C"),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "rfdiffusion3": {
            "designs": [
                {"design_id": "0", "pdb_path": str(pdb), "plddt_estimate": 0.77}
            ]
        },
        "hotspot_residues": ["A10"],
        "fold": {"plddt": 0.91},
    }

    assert extract_interface_contacts(payload) == pytest.approx(1.0)
    assert extract_target_binder_min_distance(payload) == pytest.approx(1.5)
    assert extract_clash_score(payload) == pytest.approx(1000.0)
    assert extract_interface_sasa(payload) is not None
    assert extract_interface_sasa(payload) > 0
    assert extract_hotspot_satisfaction(payload) == pytest.approx(1.0)
    assert extract_complex_confidence(payload) == pytest.approx(0.77)
    assert extract_binder_monomer_confidence(payload) == pytest.approx(0.91)


def test_extractors_cover_every_metric_enum_value() -> None:
    for metric in Metric:
        assert metric in EXTRACTORS

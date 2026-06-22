"""Nanobody-vs-GPCR workflow: hit gate, DB v5 round-trip, report rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw import db
from proteinclaw.agent.triage import DesignRecord, TargetInfo, TriageResult
from proteinclaw.report import _NANOBODY_GATE, _is_hit, render_report


def _nb_hit() -> DesignRecord:
    """A nanobody design clearing the nanobody gate on every metric."""
    return DesignRecord(
        sequence="QVQLVESGGG" * 12, binder_length=120,
        af2_complex_plddt=90.0, af2_ipsae=0.7, af2_iptm=0.65,
        interface_plddt=89.0, h3_plddt=88.0, cdr_contact_fraction=0.85,
        interface_bsa=750.0, clash_score=5.0, hotspot_satisfaction=0.40,  # below mini-binder bar
        binder_type="nanobody", framework="h-NbBCII10", cdr3_seq="VRGYFMRL",
        predicted_kd_nm=42.0, predicted_dg=-9.1, rank=1,
    )


def _nb_miss() -> DesignRecord:
    """Good complex pLDDT but framework-mediated interface (low CDR fraction)."""
    return DesignRecord(
        sequence="EVQLVESGGG" * 12, binder_length=120,
        af2_complex_plddt=90.0, af2_ipsae=0.7, af2_iptm=0.65,
        interface_plddt=89.0, h3_plddt=88.0, cdr_contact_fraction=0.30,
        interface_bsa=750.0, binder_type="nanobody", rank=2,
    )


def test_nanobody_gate_selected_by_binder_type() -> None:
    assert _is_hit(_nb_hit()) is True
    # Low CDR-contact fraction fails the nanobody gate even with good pLDDT/ipTM.
    assert _is_hit(_nb_miss()) is False


def test_nanobody_design_would_fail_minibinder_gate() -> None:
    """A real nanobody hit (ipSAE 0.7, hotspot 0.4) fails the strict mini-binder
    gate — proving the per-type gate is load-bearing, not cosmetic."""
    d = _nb_hit()
    d.binder_type = "minibinder"  # force the wrong gate
    assert _is_hit(d) is False


def test_missing_cdr_metric_fails_nanobody_gate() -> None:
    d = _nb_hit()
    d.h3_plddt = None
    assert _is_hit(d) is False


def test_report_renders_nanobody_columns(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(target=TargetInfo(pdb_id="MRGPRX2"), designs=[_nb_hit(), _nb_miss()])
    render_report(triage, run_id="rNB", prompt="design a nanobody against MRGPRX2", output_path=out)
    text = out.read_text()
    assert "nanobody gate" in text
    assert ">CDR contact</th>" in text and ">H3 pLDDT</th>" in text and ">CDR3</th>" in text
    assert ">KD nM*</th>" in text  # advisory KD column
    assert ">hits / 2</span><span class=\"metric-value\">1</span>" in text


def test_minibinder_report_unchanged(tmp_path: Path) -> None:
    """A mini-binder run must still render the original columns (no regression)."""
    out = tmp_path / "report.html"
    mb = DesignRecord(
        sequence="MKQGV" * 13, binder_length=65, af2_complex_plddt=96.0,
        af2_ipsae=0.95, af2_iptm=0.80, hotspot_satisfaction=0.85,
        interface_bsa=950.0, rank=1,
    )
    triage = TriageResult(target=TargetInfo(pdb_id="5JDS"), designs=[mb])
    render_report(triage, run_id="rMB", prompt="x", output_path=out)
    text = out.read_text()
    assert "strict hit gate" in text and "nanobody gate" not in text
    assert ">hotspot</th>" in text and ">pDockQ2</th>" in text
    assert ">CDR contact</th>" not in text


def test_db_v5_round_trips_nanobody_fields(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "runs.db")
    assert db.schema_version(conn) == 5
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    db.record_design(
        conn, run_id="r1", rank=1, plddt_af2_complex=90.0,
        binder_type="nanobody", framework="h-NbBCII10", cdr3_seq="VRGYFMRL",
        interface_plddt=89.0, h3_plddt=88.0, cdr_contact_fraction=0.85,
        predicted_kd_nm=42.0, predicted_dg=-9.1, sequence="QVQLV",
    )
    d = db.get_run(conn, "r1")["designs"][0]
    assert d["binder_type"] == "nanobody"
    assert d["framework"] == "h-NbBCII10"
    assert d["cdr3_seq"] == "VRGYFMRL"
    assert d["interface_plddt"] == 89.0
    assert d["cdr_contact_fraction"] == 0.85
    assert d["predicted_kd_nm"] == 42.0


def _interpenetrating_pose() -> DesignRecord:
    """The signature failure from run 48045e097ad0 rank-1: good pLDDT/ipTM-ish
    but an interpenetrating pose — huge BSA + high clash. Must NOT be a hit."""
    return DesignRecord(
        sequence="QVQLVESGGG" * 12, binder_length=117,
        af2_complex_plddt=90.0, af2_ipsae=0.7, af2_iptm=0.65,
        interface_plddt=89.0, h3_plddt=88.0, cdr_contact_fraction=0.76,
        interface_bsa=2967.0, clash_score=63.0,  # non-physical
        binder_type="nanobody", predicted_kd_nm=0.04, rank=1,
    )


def test_interpenetrating_pose_fails_gate() -> None:
    """BSA upper-bound + clash ceiling reject the membrane-in-vacuum artifact
    that previously ranked #1 with a fake 0.04 nM KD."""
    d = _interpenetrating_pose()
    assert _is_hit(d) is False
    # Over-large BSA alone fails (even with a clean clash score).
    d2 = _nb_hit()
    d2.interface_bsa = 2500.0
    assert _is_hit(d2) is False
    # High clash alone fails (even with in-range BSA).
    d3 = _nb_hit()
    d3.clash_score = 80.0
    assert _is_hit(d3) is False
    # Missing clash score fails (can't confirm physicality).
    d4 = _nb_hit()
    d4.clash_score = None
    assert _is_hit(d4) is False


def test_report_flags_untrustworthy_kd(tmp_path: Path) -> None:
    """A high-clash pose's advisory KD is marked ⚠ in the report."""
    triage = TriageResult(target=TargetInfo(pdb_id="8E0G"), designs=[_interpenetrating_pose()])
    out = tmp_path / "report.html"
    render_report(triage, run_id="rWarn", prompt="x", output_path=out)
    assert "⚠" in out.read_text()


def test_nanobody_gate_thresholds_documented() -> None:
    # Guard against accidental edits to the provisional nanobody gate.
    assert _NANOBODY_GATE["ipsae"] == 0.6
    assert _NANOBODY_GATE["cdr_contact_fraction"] == 0.70
    assert _NANOBODY_GATE["bsa_max"] == 1400.0
    assert _NANOBODY_GATE["clash_max"] == 50.0

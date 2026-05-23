"""HTML report renderer — smoke test."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.agent.triage import DesignRecord, TargetInfo, TriageResult
from proteinclaw.report import render_report


def _triage() -> TriageResult:
    return TriageResult(
        target=TargetInfo(pdb_id="5JDS", chain="A", crop="18-134", title="PD-L1 IgV"),
        designs=[
            DesignRecord(
                sequence="MKQGV" * 13, binder_length=65,
                esm_monomer_plddt=78.0, af2_complex_plddt=85.3,
                af2_complex_pdb=None, msa_degraded=False,
            ),
            DesignRecord(
                sequence="MKQGI" * 13, binder_length=65,
                esm_monomer_plddt=72.0, af2_complex_plddt=70.5,
                af2_complex_pdb=None, msa_degraded=True,
            ),
            DesignRecord(
                sequence="MKQGZ" * 13, binder_length=65,
                esm_monomer_plddt=80.0, af2_complex_plddt=None,
            ),
        ],
        esm_threshold_used=70,
    )


def test_renders_self_contained_html(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    render_report(_triage(), run_id="r123", prompt="design binder", output_path=out)
    text = out.read_text()
    # Smoke: file is non-trivial HTML5.
    assert text.startswith("<!doctype html>")
    assert "</html>" in text
    # Header values.
    assert "r123" in text
    assert "5JDS" in text
    assert "PD-L1 IgV" in text
    # Rank table.
    assert "85.3" in text
    # Degraded marker.
    assert "DEGRADED" in text
    # Unranked design appears in the second table block.
    assert "unranked designs" in text
    # Scatter SVG.
    assert "<svg" in text and "ESM monomer pLDDT" in text and "RANKING SIGNAL" in text


def test_handles_empty_designs(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(target=TargetInfo(pdb_id="5JDS"), designs=[])
    render_report(triage, run_id="rNone", prompt="x", output_path=out)
    text = out.read_text()
    assert "no AF2-ranked designs" in text or "no top design" in text


def test_inlines_top_pdb_when_present(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    pdb = tmp_path / "top.pdb"
    pdb.write_text("HEADER FAKE\nATOM      1  CA  MET A   1\nEND\n")
    triage = TriageResult(
        target=TargetInfo(pdb_id="5JDS"),
        designs=[
            DesignRecord(
                sequence="AAAA", binder_length=4,
                af2_complex_plddt=80.0, af2_complex_pdb=str(pdb),
            )
        ],
    )
    render_report(triage, run_id="r1", prompt="x", output_path=out)
    text = out.read_text()
    # Mol* viewer mount and the inlined PDB text both present.
    assert "molstar-viewer" in text
    assert "HEADER FAKE" in text

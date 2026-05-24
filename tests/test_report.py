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
                af2_ipsae=0.513, af2_iptm=0.72,
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
    # Degraded marker on the MSA-degraded design.
    assert "MSA degraded" in text
    # Candidates table + ranking-signal callout in the section heading.
    assert "Candidates" in text
    assert "by AF2 complex pLDDT" in text


def test_ipsae_column_renders(tmp_path: Path) -> None:
    """The candidates table shows an ipSAE column with the per-design value."""
    out = tmp_path / "report.html"
    triage = TriageResult(
        target=TargetInfo(pdb_id="5JDS", chain="A", crop="18-134", title="PD-L1"),
        designs=[
            DesignRecord(
                sequence="MKQGV" * 13, binder_length=65,
                esm_monomer_plddt=78.0, af2_complex_plddt=85.3,
                af2_ipsae=0.513, af2_iptm=0.72,
            )
        ],
        esm_threshold_used=70,
    )
    render_report(triage, run_id="r1", prompt="x", output_path=out)
    text = out.read_text()
    assert "ipSAE" in text          # column header
    assert "0.513" in text          # rank-1 value, 3 dp
    assert "Candidates" in text


def test_handles_empty_designs(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(target=TargetInfo(pdb_id="5JDS"), designs=[])
    render_report(triage, run_id="rNone", prompt="x", output_path=out)
    text = out.read_text().lower()
    # Empty-state: the candidates section says "no ranked designs" and the
    # viewer says there's no structure to render.
    assert "no ranked designs" in text
    assert "no structure to render" in text


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

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


def _hit_design() -> DesignRecord:
    """A design that clears the strict combined gate on every metric."""
    return DesignRecord(
        sequence="MKQGV" * 13, binder_length=65,
        esm_monomer_plddt=88.0, af2_complex_plddt=96.0,
        af2_ipsae=0.65, af2_iptm=0.80, af2_pdockq=0.5, af2_pdockq2=0.6,
        hotspot_satisfaction=0.85, interface_bsa=950.0, clash_score=3.0,
        n_interface_contacts=42, af2_complex_pdb=None, rank=1,
    )


def _miss_design() -> DesignRecord:
    """High pLDDT but a weak interface — fails the gate on ipSAE/ipTM."""
    return DesignRecord(
        sequence="AAAAA" * 13, binder_length=65,
        esm_monomer_plddt=80.0, af2_complex_plddt=95.0,
        af2_ipsae=0.25, af2_iptm=0.40, hotspot_satisfaction=0.30,
        interface_bsa=400.0, clash_score=12.0, n_interface_contacts=10,
        af2_complex_pdb=None, rank=2,
    )


def test_is_hit_strict_gate() -> None:
    from proteinclaw.report import _is_hit

    assert _is_hit(_hit_design()) is True
    assert _is_hit(_miss_design()) is False
    # A missing metric fails the gate (can't confirm a hit you can't measure).
    d = _hit_design()
    d.af2_ipsae = None
    assert _is_hit(d) is False


def test_metric_suite_and_hit_count(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(
        target=TargetInfo(pdb_id="5JDS"),
        designs=[_hit_design(), _miss_design()],
    )
    render_report(triage, run_id="r1", prompt="x", output_path=out)
    text = out.read_text()
    # Best-of metric suite in the header, against the strict gate.
    assert "metric-suite" in text
    assert "best ipSAE" in text and "best ipTM" in text and "pDockQ2" in text
    # hits/2 == 1 (only the hit design clears all gates).
    assert ">hits / 2</span><span class=\"metric-value\">1</span>" in text
    # Pass/fail colouring is emitted.
    assert "metric-ok" in text and "metric-bad" in text
    # Candidates table now has the hit column + new metric columns.
    assert ">hit</th>" in text and ">ipTM</th>" in text and ">pDockQ</th>" in text
    assert "cell-ok" in text and "cell-bad" in text


def test_plan_and_trace_tabs(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(target=TargetInfo(pdb_id="5JDS"), designs=[_hit_design()])
    plan = "# Run plan\n## Debate\n- Challenge: loop vs flat face\n- Converged: helical."
    events = [
        {"type": "run_started"},
        {"type": "subagent_spawn", "subagent_type": "research", "description": "scout"},
        {"type": "tool_use", "name": "design_rfdiffusion3", "input": {"x": 1}},
    ]
    render_report(
        triage, run_id="r1", prompt="x", output_path=out,
        extra_meta={"plan_md": plan, "trace_events": events},
    )
    text = out.read_text()
    # Tab nav + both panels.
    assert 'data-tab="tab-report"' in text and 'data-tab="tab-trace"' in text
    assert 'id="tab-trace"' in text
    # Plan & debate inlined verbatim.
    assert "Plan &amp; debate" in text
    assert "Challenge: loop vs flat face" in text
    # Raw-trace tab loads the events client-side.
    assert "Raw trace" in text and "TRACE_EVENTS=" in text
    assert "3 events from trace.jsonl" in text


def test_plan_seed_template_shows_placeholder(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    triage = TriageResult(target=TargetInfo(pdb_id="5JDS"), designs=[_hit_design()])
    seed = "# Plan\n\nThe Claude agent's initial plan and reflections during this run."
    render_report(triage, run_id="r1", prompt="x", output_path=out,
                  extra_meta={"plan_md": seed})
    text = out.read_text()
    assert "never reached the" in text  # honest empty-state, not the seed text


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

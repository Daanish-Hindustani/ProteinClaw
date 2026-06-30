"""Triage — parse a synthetic trace, rank designs, stage PDBs, write result.json."""

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.agent.triage import (
    parse_trace,
    stage_ranked_designs,
    write_result_json,
)
from proteinclaw.agent.trace import TraceWriter


def _envelope(payload: dict) -> list:
    return [{"type": "text", "text": json.dumps(payload)}]


def _trace_lines(events: list[dict]) -> str:
    import time

    return "\n".join(
        json.dumps({"ts": time.time(), **e}) for e in events
    ) + "\n"


def test_parse_full_pipeline_trace(tmp_path: Path) -> None:
    # Fabricate a trace covering all four "real" tools, including one
    # MSA-degraded AF2 and one AF2 that errored.
    seq_good = "MKQGV" * 13       # 65 aa
    seq_degraded = "MKQGI" * 13   # 65 aa, msa_degraded
    seq_failed = "MKQGZ" * 13     # 65 aa, AF2 returns error envelope

    events = [
        # data_pdb_fetch
        {
            "type": "tool_use",
            "tool_use_id": "u_pdb",
            "name": "proteinclaw_data_pdb_fetch",
            "input": {"pdb_id": "5JDS", "chain": "A", "crop": "18-134"},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_pdb",
            "content": _envelope({"pdb_id": "5JDS", "chain": "A", "crop": "18-134"}),
        },
        # data_rcsb_search (for target title)
        {
            "type": "tool_use",
            "tool_use_id": "u_rcsb",
            "name": "proteinclaw_data_rcsb_search",
            "input": {"query": "PD-L1 IgV domain"},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_rcsb",
            "content": _envelope({"candidates": [{"title": "PD-L1 IgV V76T"}]}),
        },
        # MPNN — returns 3 sequences
        {
            "type": "tool_use",
            "tool_use_id": "u_mpnn",
            "name": "proteinclaw_design_proteinmpnn",
            "input": {"backbone_pdb": "/workspace/rfdiffusion3_0/design_0.pdb"},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_mpnn",
            "content": _envelope({
                "sequences": [seq_good, seq_degraded, seq_failed],
            }),
        },
        # ESMFold — batch over all 3
        {
            "type": "tool_use",
            "tool_use_id": "u_esm",
            "name": "proteinclaw_structure_esmfold",
            "input": {"sequences": [seq_good, seq_degraded, seq_failed]},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_esm",
            "content": _envelope({
                "predictions": [
                    {"sequence": seq_good, "confidence": 78.2,
                     "pdb_path": "/workspace/esmfold_0/000_MKQGV.pdb",
                     "num_residues": 65},
                    {"sequence": seq_degraded, "confidence": 72.0,
                     "pdb_path": "/workspace/esmfold_0/001_MKQGI.pdb",
                     "num_residues": 65},
                    {"sequence": seq_failed, "confidence": 80.0,
                     "pdb_path": "/workspace/esmfold_0/002_MKQGZ.pdb",
                     "num_residues": 65},
                ]
            }),
        },
        # AF2 #1 — good
        {
            "type": "tool_use",
            "tool_use_id": "u_af2a",
            "name": "proteinclaw_structure_alphafold2_multimer",
            "input": {"binder_sequence": seq_good},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_af2a",
            "content": _envelope({
                "complex_confidence": 85.3,
                "target_chain_plddt": 90.1,
                "msa_degraded": False,
                "complex_pdb_path": "/tmp/no_such_pdb_a.pdb",
                "out_folder": str(tmp_path / "af2_good"),
            }),
        },
        # AF-M screen confirmation for AF2 #1.
        {
            "type": "tool_use",
            "tool_use_id": "u_afm_score",
            "name": "proteinclaw_analysis_afm_screen_score",
            "input": {"output_dir": str(tmp_path / "af2_good")},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_afm_score",
            "content": _envelope({
                "output_dir": str(tmp_path / "af2_good"),
                "combo_feature": 0.123456,
                "avg_model_support": 3.2,
                "n_unique_contacts": 42,
                "avg_metrics": {
                    "avg_interface_pae": 5.4,
                    "avg_interface_plddt": 88.1,
                    "iptm": 0.66,
                    "rtm": 0.64,
                    "pdockq": 0.31,
                },
            }),
        },
        # AF2 #2 — degraded
        {
            "type": "tool_use",
            "tool_use_id": "u_af2b",
            "name": "proteinclaw_structure_alphafold2_multimer",
            "input": {"binder_sequence": seq_degraded},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_af2b",
            "content": _envelope({
                "complex_confidence": 70.5,
                "target_chain_plddt": 88.0,
                "msa_degraded": True,
                "complex_pdb_path": "/tmp/no_such_pdb_b.pdb",
            }),
        },
        # AF2 #3 — error
        {
            "type": "tool_use",
            "tool_use_id": "u_af2c",
            "name": "proteinclaw_structure_alphafold2_multimer",
            "input": {"binder_sequence": seq_failed},
        },
        {
            "type": "tool_result",
            "tool_use_id": "u_af2c",
            "content": _envelope({
                "summary": "Error: AF2 OOM",
                "error": "oom",
            }),
        },
        # Agent message mentioning the ESM threshold so triage picks it up.
        {
            "type": "assistant_text",
            "text": "I will use an ESMFold pLDDT threshold of 70 for this run.",
        },
    ]
    trace = tmp_path / "trace.jsonl"
    trace.write_text(_trace_lines(events))

    triage = parse_trace(trace)
    assert triage.target.pdb_id == "5JDS"
    assert triage.target.chain == "A"
    assert triage.target.crop == "18-134"
    assert triage.target.title == "PD-L1 IgV V76T"

    # 3 designs total; 2 ranked (good + degraded); 1 unranked (AF2 errored)
    assert len(triage.designs) == 3
    assert len(triage.ranked_designs) == 2
    assert len(triage.unranked_designs) == 1
    # Highest af2 wins rank 1.
    top = triage.ranked_designs[0]
    assert top.af2_complex_plddt == 85.3
    assert top.msa_degraded is False
    assert top.afm_combo_feature == 0.123456
    assert top.afm_avg_model_support == 3.2
    assert top.afm_avg_interface_pae == 5.4
    # esm join worked too.
    assert top.esm_monomer_plddt == 78.2
    # Threshold detection (heuristic).
    assert triage.esm_threshold_used == 70

    # Note for failed AF2.
    assert any("AF2 failed" in n for n in triage.notes)


def test_stage_ranked_designs_copies_pdbs(tmp_path: Path) -> None:
    """Verify stage_ranked_designs copies real PDB files into rank_NN_*.pdb."""
    # Create two dummy PDB files.
    src1 = tmp_path / "src1.pdb"
    src2 = tmp_path / "src2.pdb"
    src1.write_text("ATOM      1  CA  MET A   1\n")
    src2.write_text("ATOM      1  CA  ALA A   1\n")

    # Build a TriageResult with both ranked.
    from proteinclaw.agent.triage import DesignRecord, TargetInfo, TriageResult

    tr = TriageResult(
        target=TargetInfo(),
        designs=[
            DesignRecord(
                sequence="AAAAA", binder_length=5,
                af2_complex_plddt=80.0, af2_complex_pdb=str(src1),
            ),
            DesignRecord(
                sequence="BBBBB", binder_length=5,
                af2_complex_plddt=70.0, af2_complex_pdb=str(src2),
            ),
        ],
    )
    designs_dir = tmp_path / "designs"
    staged = stage_ranked_designs(tr, designs_dir)
    assert len(staged) == 2
    assert (designs_dir / "rank_01_AAAAA.pdb").exists()
    assert (designs_dir / "rank_02_BBBBB.pdb").exists()
    # Records were updated to point at staged copies.
    assert staged[0].af2_complex_pdb.endswith("rank_01_AAAAA.pdb")


def test_write_result_json_round_trip(tmp_path: Path) -> None:
    from proteinclaw.agent.triage import DesignRecord, TargetInfo, TriageResult

    tr = TriageResult(
        target=TargetInfo(pdb_id="5JDS", chain="A"),
        designs=[
            DesignRecord(sequence="A" * 60, binder_length=60,
                         esm_monomer_plddt=75.0, af2_complex_plddt=82.4),
        ],
        esm_threshold_used=70,
    )
    out = tmp_path / "result.json"
    write_result_json(tr, out)
    loaded = json.loads(out.read_text())
    assert loaded["target"]["pdb_id"] == "5JDS"
    assert loaded["num_designs"] == 1
    assert loaded["num_ranked"] == 1
    assert loaded["designs"][0]["rank"] == 1


def test_parse_empty_trace(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text("")
    triage = parse_trace(trace)
    assert triage.designs == []
    assert triage.ranked_designs == []


def test_target_chain_crop_back_filled_by_later_fetch(tmp_path: Path) -> None:
    """Agent often calls pdb_fetch twice: first to inspect, then with chain+crop.
    Triage should populate chain/crop from the second call when the first had None."""
    events = [
        {"type": "tool_use", "tool_use_id": "u1",
         "name": "proteinclaw_data_pdb_fetch",
         "input": {"pdb_id": "5JDS"}},
        {"type": "tool_result", "tool_use_id": "u1",
         "content": _envelope({"pdb_id": "5JDS"})},
        {"type": "tool_use", "tool_use_id": "u2",
         "name": "proteinclaw_data_pdb_fetch",
         "input": {"pdb_id": "5JDS", "chain": "A", "crop": "18-134"}},
        {"type": "tool_result", "tool_use_id": "u2",
         "content": _envelope({"pdb_id": "5JDS", "chain": "A", "crop": "18-134"})},
    ]
    trace = tmp_path / "trace.jsonl"
    trace.write_text(_trace_lines(events))
    triage = parse_trace(trace)
    assert triage.target.pdb_id == "5JDS"
    assert triage.target.chain == "A"
    assert triage.target.crop == "18-134"


def test_target_first_fetch_chain_crop_not_overwritten(tmp_path: Path) -> None:
    """If the first pdb_fetch already had chain+crop, later calls don't overwrite."""
    events = [
        {"type": "tool_use", "tool_use_id": "u1",
         "name": "proteinclaw_data_pdb_fetch",
         "input": {"pdb_id": "5JDS", "chain": "A", "crop": "18-134"}},
        {"type": "tool_result", "tool_use_id": "u1",
         "content": _envelope({"pdb_id": "5JDS", "chain": "A", "crop": "18-134"})},
        {"type": "tool_use", "tool_use_id": "u2",
         "name": "proteinclaw_data_pdb_fetch",
         "input": {"pdb_id": "5JDS", "chain": "B"}},
        {"type": "tool_result", "tool_use_id": "u2",
         "content": _envelope({"pdb_id": "5JDS", "chain": "B"})},
    ]
    trace = tmp_path / "trace.jsonl"
    trace.write_text(_trace_lines(events))
    triage = parse_trace(trace)
    assert triage.target.chain == "A"
    assert triage.target.crop == "18-134"


def test_large_esmfold_envelope_joins_esm_plddt(tmp_path: Path) -> None:
    """Regression: a big ESMFold batch envelope written through the real
    TraceWriter (which trims long strings) must still be parseable by
    triage, so esm_monomer_plddt joins onto the design. Previously the
    4000-char trim corrupted the JSON and esm_monomer_plddt stayed None."""
    # Unique 2-char suffix per design so sequences don't collide.
    base = "MRARLYALAEAAFKAAAAGDV" * 3
    seqs = [base + chr(65 + i // 20) + chr(65 + i % 20) for i in range(48)]
    target = seqs[0]
    esm_env = {
        "summary": "ESMFold: 48 structures",
        "predictions": [
            {
                "index": i, "sequence": s, "pdb_path": f"/ws/{i:03d}.pdb",
                "confidence": 70.0 + i * 0.1,
                "per_residue_plddt": [round(60 + (j % 30) * 0.7, 2) for j in range(len(s))],
            }
            for i, s in enumerate(seqs)
        ],
    }
    trace = tmp_path / "trace.jsonl"
    with TraceWriter(trace) as t:
        t.tool_use(tool_use_id="u_mpnn",
                   name="proteinclaw_design_proteinmpnn", input={})
        t.tool_result(tool_use_id="u_mpnn", is_error=False,
                      content=[{"type": "text", "text": json.dumps({"sequences": seqs})}])
        t.tool_use(tool_use_id="u_esm",
                   name="proteinclaw_structure_esmfold", input={})
        t.tool_result(tool_use_id="u_esm", is_error=False,
                      content=[{"type": "text", "text": json.dumps(esm_env)}])
        t.tool_use(tool_use_id="u_af2",
                   name="proteinclaw_structure_alphafold2_multimer",
                   input={"binder_sequence": target})
        t.tool_result(tool_use_id="u_af2", is_error=False,
                      content=[{"type": "text", "text": json.dumps({
                          "complex_confidence": 88.0, "target_chain_plddt": 90.0,
                          "complex_pdb_path": "/ws/af2.pdb"})}])

    triage = parse_trace(trace)
    top = triage.ranked_designs[0]
    assert top.sequence == target
    assert top.esm_monomer_plddt == 70.0  # joined from the (untruncated) ESM batch


def test_af2_ipsae_metrics_absorbed_ranking_unchanged(tmp_path: Path) -> None:
    """ipSAE/iptm/pdockq/lis flow into DesignRecord; ranking stays on pLDDT."""
    seq_hi, seq_lo = "AAAAAAAAAA", "CCCCCCCCCC"
    events = [
        # Higher complex pLDDT but LOW ipSAE (false-positive shape).
        {"type": "tool_use", "tool_use_id": "u1",
         "name": "proteinclaw_structure_alphafold2_multimer",
         "input": {"binder_sequence": seq_hi}},
        {"type": "tool_result", "tool_use_id": "u1", "content": _envelope({
            "complex_confidence": 88.0, "target_chain_plddt": 90.0,
            "ipsae": 0.12, "iptm": 0.40, "pdockq": 0.10, "lis": 0.20,
            "complex_pdb_path": "/tmp/hi.pdb"})},
        # Lower pLDDT but strong interface.
        {"type": "tool_use", "tool_use_id": "u2",
         "name": "proteinclaw_structure_alphafold2_multimer",
         "input": {"binder_sequence": seq_lo}},
        {"type": "tool_result", "tool_use_id": "u2", "content": _envelope({
            "complex_confidence": 80.0, "target_chain_plddt": 85.0,
            "ipsae": 0.61, "iptm": 0.82, "pdockq": 0.45, "lis": 0.55,
            "complex_pdb_path": "/tmp/lo.pdb"})},
    ]
    trace = tmp_path / "trace.jsonl"
    trace.write_text(_trace_lines(events))

    triage = parse_trace(trace)
    ranked = triage.ranked_designs
    # Ranking is unchanged — still by complex_confidence (88.0 first).
    assert [round(d.af2_complex_plddt) for d in ranked] == [88, 80]
    top = ranked[0]
    assert top.af2_ipsae == 0.12 and top.af2_iptm == 0.40
    assert top.af2_pdockq == 0.10 and top.af2_lis == 0.20
    # The metrics survive serialization into result.json.
    d0 = triage.to_dict()["designs"][0]
    assert d0["af2_ipsae"] == 0.12 and d0["af2_iptm"] == 0.40


def test_nanobody_library_marks_binder_type_and_cdr_index(tmp_path: Path) -> None:
    """A nanobody_library result populates cdr_index; the matching AF2 design is
    tagged binder_type=nanobody with framework/cdr3 carried through."""
    nb_seq = "QVQLVESGGG" + "A" * 30 + "WFRQAPGQGLEAVAA" + "B" * 8
    lib = {
        "framework": "h-NbBCII10",
        "source": "generated",
        "designs": [
            {"id": "nb_0000", "sequence": nb_seq, "cdr1": [11, 13],
             "cdr2": [40, 47], "cdr3": [50, 55], "cdr3_seq": "BBBBBB"},
        ],
    }
    libjson = tmp_path / "library.json"
    libjson.write_text(json.dumps(lib))
    events = [
        {"type": "tool_use", "tool_use_id": "ulib",
         "name": "proteinclaw_design_nanobody_library",
         "input": {"n_designs": 1}},
        {"type": "tool_result", "tool_use_id": "ulib", "content": _envelope({
            "library_json_path": str(libjson), "n_designs": 1,
            "framework": "h-NbBCII10"})},
        {"type": "tool_use", "tool_use_id": "uaf2",
         "name": "proteinclaw_structure_alphafold2_multimer",
         "input": {"binder_sequence": nb_seq}},
        {"type": "tool_result", "tool_use_id": "uaf2", "content": _envelope({
            "complex_confidence": 90.0, "ipsae": 0.7, "iptm": 0.65,
            "complex_pdb_path": "/tmp/nb.pdb"})},
    ]
    trace = tmp_path / "trace.jsonl"
    trace.write_text(_trace_lines(events))

    triage = parse_trace(trace)
    assert nb_seq in triage.cdr_index
    assert triage.cdr_index[nb_seq]["cdr3"] == [50, 55]
    d = triage.ranked_designs[0]
    assert d.binder_type == "nanobody"
    assert d.framework == "h-NbBCII10"
    assert d.cdr3_seq == "BBBBBB"

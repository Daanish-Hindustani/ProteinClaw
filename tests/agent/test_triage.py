"""Triage — parse a synthetic trace, rank designs, stage PDBs, write result.json."""

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.agent.triage import (
    parse_trace,
    stage_ranked_designs,
    write_result_json,
)


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
            "name": "mcp__proteinclaw_tools__data_pdb_fetch",
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
            "name": "mcp__proteinclaw_tools__data_rcsb_search",
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
            "name": "mcp__proteinclaw_tools__design_proteinmpnn",
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
            "name": "mcp__proteinclaw_tools__structure_esmfold",
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
            "name": "mcp__proteinclaw_tools__structure_alphafold2_multimer",
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
            }),
        },
        # AF2 #2 — degraded
        {
            "type": "tool_use",
            "tool_use_id": "u_af2b",
            "name": "mcp__proteinclaw_tools__structure_alphafold2_multimer",
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
            "name": "mcp__proteinclaw_tools__structure_alphafold2_multimer",
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

"""Tests for the five protein-design tool wrappers (mock backends).

For each tool we verify (a) input schema validation, (b) output shape,
(c) determinism: same input → same output. The mock backends are seeded
by their inputs so they must be reproducible run-to-run.
"""

from __future__ import annotations

import pytest

from proteinclaw.tools.base_tool import ToolExecutionError, ToolStatus
from proteinclaw.tools.protein.alphafold import AlphaFold, FoldOutputs
from proteinclaw.tools.protein.foldseek import Foldseek, FoldseekInputs, FoldseekOutputs
from proteinclaw.tools.protein.protein_mpnn import ProteinMPNN, ProteinMPNNOutputs
from proteinclaw.tools.protein.rcsb import RCSB, RCSBOutputs
from proteinclaw.tools.protein.rfdiffusion3 import RFDiffusion3, RFDiffusionOutputs


async def test_rfdiffusion_mock_determinism_and_shape() -> None:
    tool = RFDiffusion3()
    inputs = {
        "target_pdb_path": "1ABC",
        "contigs": "10-20/A1-50/30-40",
        "num_designs": 3,
    }
    a = await tool.invoke(inputs)
    b = await tool.invoke(inputs)
    assert a.status == ToolStatus.SUCCESS
    assert a.payload == b.payload  # determinism
    parsed = RFDiffusionOutputs.model_validate(a.payload)
    assert len(parsed.designs) == 3
    for d in parsed.designs:
        assert 0.0 <= d.plddt_estimate <= 1.0
        assert d.pdb_path.endswith(".pdb")


async def test_rfdiffusion_input_validation() -> None:
    with pytest.raises(ToolExecutionError):
        await RFDiffusion3().invoke({"target_pdb_path": "X"})  # missing required


async def test_rfdiffusion_num_designs_bounds() -> None:
    with pytest.raises(ToolExecutionError):
        await RFDiffusion3().invoke({"target_pdb_path": "X", "contigs": "A1", "num_designs": 0})


@pytest.mark.parametrize(
    "bad_contigs",
    [
        "A1=evil",  # Hydra '=' breakout
        "A1] evil=stuff [",  # bracket escape
        "A1; rm -rf /",  # shell metacharacters
        "A1\nevil",  # newline injection
        "",  # empty
    ],
)
async def test_rfdiffusion_rejects_unsafe_contigs(bad_contigs: str) -> None:
    with pytest.raises(ToolExecutionError):
        await RFDiffusion3().invoke({"target_pdb_path": "1ABC", "contigs": bad_contigs})


@pytest.mark.parametrize(
    "bad_path",
    [
        "1ABC; rm -rf /",
        "/etc/passwd ",  # trailing space
        "path with spaces",
        "evil=value",  # Hydra-style override character
        "",
    ],
)
async def test_rfdiffusion_rejects_unsafe_target_pdb_path(bad_path: str) -> None:
    with pytest.raises(ToolExecutionError):
        await RFDiffusion3().invoke({"target_pdb_path": bad_path, "contigs": "A1-50"})


@pytest.mark.parametrize(
    "bad_residue",
    ["A45=evil", "A; rm", "45A", " A45", "A", "45"],
)
async def test_rfdiffusion_rejects_unsafe_hotspot(bad_residue: str) -> None:
    with pytest.raises(ToolExecutionError):
        await RFDiffusion3().invoke(
            {
                "target_pdb_path": "1ABC",
                "contigs": "A1-50",
                "hotspot_residues": [bad_residue],
            }
        )


async def test_protein_mpnn_mock_shape_and_determinism() -> None:
    tool = ProteinMPNN()
    inputs = {"backbone_pdb_path": "/x.pdb", "num_sequences": 4}
    a = await tool.invoke(inputs)
    b = await tool.invoke(inputs)
    assert a.payload == b.payload
    parsed = ProteinMPNNOutputs.model_validate(a.payload)
    assert len(parsed.sequences) == 4
    for s in parsed.sequences:
        assert s.sequence
        assert all(c.isalpha() for c in s.sequence)


async def test_alphafold_mock_with_and_without_msa_differ() -> None:
    tool = AlphaFold()
    base = {"sequence": "MKVLAVAGAATG"}
    no_msa = await tool.invoke({**base, "msa": None})
    with_msa = await tool.invoke({**base, "msa": "fake-msa"})
    no_parsed = FoldOutputs.model_validate(no_msa.payload)
    yes_parsed = FoldOutputs.model_validate(with_msa.payload)
    assert "single" in no_parsed.pdb_path
    assert "msa" in yes_parsed.pdb_path
    assert no_parsed.pdb_path != yes_parsed.pdb_path


async def test_alphafold_short_sequence_rejected() -> None:
    with pytest.raises(ToolExecutionError):
        await AlphaFold().invoke({"sequence": "MKV"})  # < 10 aa min_length


async def test_foldseek_hits_sorted_descending() -> None:
    tool = Foldseek()
    out = await tool.invoke({"query_pdb_path": "/q.pdb", "max_hits": 5})
    parsed = FoldseekOutputs.model_validate(out.payload)
    assert len(parsed.hits) == 5
    tms = [h.tm_score for h in parsed.hits]
    assert tms == sorted(tms, reverse=True)


def test_foldseek_defaults_to_public_pdb100_database() -> None:
    inputs = FoldseekInputs(query_pdb_path="/q.pdb")
    assert inputs.database == "pdb100"


def test_foldseek_rejects_invalid_public_database() -> None:
    with pytest.raises(ValueError):
        FoldseekInputs(query_pdb_path="/q.pdb", database="pdb")


async def test_rcsb_normalizes_id_to_upper() -> None:
    tool = RCSB()
    out = await tool.invoke({"pdb_id": "1abc"})
    parsed = RCSBOutputs.model_validate(out.payload)
    assert parsed.pdb_id == "1ABC"
    assert parsed.length == len(parsed.sequence)


async def test_rcsb_invalid_id_rejected() -> None:
    with pytest.raises(ToolExecutionError):
        await RCSB().invoke({"pdb_id": "TOOLONG"})


async def test_rcsb_determinism() -> None:
    a = await RCSB().invoke({"pdb_id": "2XYZ"})
    b = await RCSB().invoke({"pdb_id": "2XYZ"})
    assert a.payload == b.payload

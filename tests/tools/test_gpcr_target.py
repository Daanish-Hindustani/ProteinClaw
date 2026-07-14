from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.tools import registry
from proteinclaw.tools.gpcr_target import gpcr_hypothesis_portfolio, gpcr_target_prepare


def _atom(serial: int, chain: str, residue: int) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{float(residue):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 80.00           C"
    )


def _gpcr(tmp_path: Path) -> Path:
    path = tmp_path / "gpcr.pdb"
    lines = [_atom(i, "R", i) for i in range(1, 101)]
    lines += [_atom(100 + i, "N", i) for i in range(1, 6)]
    path.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")
    return path


def _gpcr_mmcif(tmp_path: Path, pdb_path: Path) -> Path:
    from Bio.PDB import MMCIFIO, PDBParser

    structure = PDBParser(QUIET=True).get_structure("TEST", pdb_path)
    path = tmp_path / "gpcr.cif"
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(str(path))
    return path


def _representation_kwargs(state: str) -> dict:
    return {
        "source_id": "PDB:TEST",
        "receptor_id": "TEST_RECEPTOR",
        "hypothesis_id": f"test-{state}",
        "structure_method": "cryo_em",
        "structure_resolution_angstrom": 3.1,
        "construct_context": "Full test receptor construct with no engineered fusion partners.",
        "ligand_context": "State-compatible ligand retained for structural interpretation.",
        "membrane_span_source": "UniProt test annotation",
        "unresolved_regions": "",
        "modeled_regions": "",
        "glycosylation_sites": "",
        "state_markers": [
            {
                "name": "cytoplasmic microswitch",
                "residues": "20,30",
                "observation": f"Resolved marker geometry supports the {state} test state.",
                "supports_state": state,
            }
        ],
        "experimental_evidence": [
            {
                "citation": "PDB:TEST",
                "evidence_type": "complex_structure",
                "directness": "direct_same_receptor",
                "claim": "The experimental complex directly supports this test epitope.",
            }
        ],
        "reference_complex_ids": ["PDB:TEST"],
        "reference_scaffold_ids": ["PDB:VHH1"],
        "counterstate_source_ids": ["PDB:COUNTER"],
        "confirmation_strategy": "structure_conditioned",
    }


def test_registered() -> None:
    assert registry.has_tool("data.gpcr_target_prepare")
    assert registry.has_tool("data.gpcr_hypothesis_portfolio")
    required = registry.get_tool("data.gpcr_target_prepare").parameters["required"]
    assert "target_mmcif" in required
    assert "target_pdb" not in required


def test_prepare_preserves_full_target_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda *_args: tmp_path / "out",
    )
    (tmp_path / "out").mkdir()
    pdb_path = _gpcr(tmp_path)
    result = gpcr_target_prepare(
        target_pdb=str(pdb_path),
        target_mmcif=str(_gpcr_mmcif(tmp_path, pdb_path)),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7,12",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="The selected residues define a researched extracellular pocket.",
        state_rationale="The source structure contains the adjudicated inactive receptor state.",
        session_id="gpcr-test",
        **_representation_kwargs("inactive"),
    )

    assert "error" not in result
    assert result["full_chain_preserved"] is True
    assert result["num_residues"] == 100
    prepared = Path(result["prepared_pdb_path"]).read_text()
    assert " ALA R" in prepared
    assert " ALA N" not in prepared
    manifest = json.loads(Path(result["target_manifest_path"]).read_text())
    assert manifest["binding_residues"] == [3, 7, 12]
    assert manifest["excluded_residues"] == [90, 91]
    assert manifest["mapping_verified"] is True
    assert manifest["target_label_chain"] == "A"
    assert manifest["binding_residues_label"] == [3, 7, 12]
    assert manifest["topology_geometry"]["face_separation_angstrom"] > 8
    assert manifest["schema_version"] == 3
    assert manifest["experimentally_grounded"] is True
    assert manifest["target_representation"]["confirmation_state_preserved"] is True
    assert manifest["target_representation"]["counterstate_source_ids"] == ["PDB:COUNTER"]
    assert manifest["target_representation"]["state_markers"][0]["residues_label"] == [20, 30]


def test_prepare_accepts_mmcif_only_and_preserves_author_numbering(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda *_args: tmp_path / "mmcif-only",
    )
    (tmp_path / "mmcif-only").mkdir()
    pdb_path = _gpcr(tmp_path)
    mmcif_path = _gpcr_mmcif(tmp_path, pdb_path)

    result = gpcr_target_prepare(
        target_mmcif=str(mmcif_path),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7,12",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="The selected residues define a researched extracellular pocket.",
        state_rationale="The source structure contains the adjudicated inactive receptor state.",
        **_representation_kwargs("inactive"),
    )

    assert "error" not in result
    assert result["coordinate_source_format"] == "mmcif_only"
    assert result["pdb_derived_from_mmcif"] is True
    assert result["binding_residues_author"] == [3, 7, 12]
    assert result["binding_residues_label"] == [3, 7, 12]
    assert result["target_auth_chain"] == "R"
    converted = Path(result["source_pdb_path"]).read_text(encoding="utf-8")
    prepared = Path(result["prepared_pdb_path"]).read_text(encoding="utf-8")
    assert " ALA R   3 " in converted
    assert " ALA N" not in converted
    assert " ALA R   3 " in prepared
    assert Path(result["prepared_mmcif_path"]).read_bytes() == mmcif_path.read_bytes()


def test_prepare_mmcif_only_reports_missing_author_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda *_args: tmp_path / "missing-chain",
    )
    (tmp_path / "missing-chain").mkdir()
    pdb_path = _gpcr(tmp_path)
    result = gpcr_target_prepare(
        target_mmcif=str(_gpcr_mmcif(tmp_path, pdb_path)),
        target_chain="Z",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="The selected residues define a researched extracellular pocket.",
        state_rationale="The source structure contains the adjudicated inactive receptor state.",
        **_representation_kwargs("inactive"),
    )

    assert result["error"] == "invalid_args"
    assert "available author chains" in result["summary"]


def test_prepare_rejects_missing_or_overlapping_residues(tmp_path: Path) -> None:
    path = _gpcr(tmp_path)
    missing = gpcr_target_prepare(
        target_pdb=str(path),
        target_chain="R",
        binding_side="intracellular",
        receptor_state="active",
        binding_residues="3,99",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched intracellular epitope with two anchor positions.",
        state_rationale="An agonist-bound source supports the active state assignment.",
        **_representation_kwargs("active"),
    )
    assert missing["error"] == "invalid_args"

    overlap = gpcr_target_prepare(
        target_pdb=str(path),
        target_chain="R",
        binding_side="intracellular",
        receptor_state="active",
        binding_residues="3,7",
        excluded_residues="7,12",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched intracellular epitope with two anchor positions.",
        state_rationale="An agonist-bound source supports the active state assignment.",
        **_representation_kwargs("active"),
    )
    assert overlap["error"] == "invalid_args"


def test_prepare_rejects_binding_anchor_in_membrane_core(tmp_path: Path) -> None:
    path = _gpcr(tmp_path)
    result = gpcr_target_prepare(
        target_pdb=str(path),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,15",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched extracellular epitope with two anchor positions.",
        state_rationale="An antagonist-bound source supports the inactive state assignment.",
        **_representation_kwargs("inactive"),
    )
    assert result["error"] == "invalid_args"
    assert "membrane-core" in result["summary"]


def _hypothesis(
    hypothesis_id: str,
    *,
    state: str,
    side: str,
    anchors: str,
    exclusions: str,
    directness: str,
) -> dict:
    return {
        "hypothesis_id": hypothesis_id,
        "target_source_id": f"PDB:{hypothesis_id.upper()}",
        "target_chain": "R",
        "receptor_state": state,
        "binding_side": side,
        "binding_residues": anchors,
        "excluded_residues": exclusions,
        "epitope_rationale": "Resolved surface anchors reproduce an experimentally observed receptor interface.",
        "state_rationale": "Ligand context and resolved microswitches support the assigned receptor state.",
        "falsifiable_prediction": "Candidates should beat the paired control while retaining the intended face contacts.",
        "dominant_risk": "The selected receptor construct may over-stabilize the observed conformation.",
        "distinguishing_variable": "receptor_state",
        "expected_information_gain": "high",
        "experimental_evidence": [
            {
                "citation": f"PDB:{hypothesis_id.upper()}",
                "evidence_type": "complex_structure",
                "directness": directness,
                "claim": "The observed complex provides residue-level evidence for this hypothesis.",
            }
        ],
        "reference_complex_ids": [f"PDB:{hypothesis_id.upper()}"],
        "reference_scaffold_ids": ["PDB:VHH1"],
        "counterstate_source_ids": ["PDB:COUNTER"],
        "confirmation_strategy": "structure_conditioned",
        "negative_control": {
            "control_type": "state_mismatch",
            "description": "Use the same candidate against the experimentally resolved counterstate.",
            "discriminating_result": "The intended state must score reproducibly above the counterstate control.",
        },
    }


def test_hypothesis_portfolio_explores_broadly_before_deep_dive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda *_args: tmp_path / "portfolio",
    )
    (tmp_path / "portfolio").mkdir()
    result = gpcr_hypothesis_portfolio(
        receptor_id="TEST_RECEPTOR",
        hypotheses=[
            _hypothesis(
                "active-intracellular",
                state="active",
                side="intracellular",
                anchors="90,91",
                exclusions="3,7",
                directness="direct_same_receptor",
            ),
            _hypothesis(
                "inactive-extracellular",
                state="inactive",
                side="extracellular",
                anchors="3,7,12",
                exclusions="90,91",
                directness="homolog_transfer",
            ),
        ],
        exploration_designs_per_hypothesis=4,
        deep_dive_design_budget=12,
    )

    assert "error" not in result
    assert result["exploration_policy"]["total_design_budget"] == 8
    assert result["exploration_policy"]["advance_all_before_deep_dive"] is True
    assert result["promotion_gate"]["deep_dive_design_budget"] == 12
    assert result["promotion_gate"]["maximum_promoted_hypotheses"] == 2
    assert result["hypotheses"][0]["hypothesis_id"] == "active-intracellular"
    persisted = json.loads(Path(result["hypothesis_portfolio_path"]).read_text())
    assert persisted["hypotheses"][1]["binding_residues"] == [3, 7, 12]


def test_hypothesis_portfolio_rejects_duplicates_and_ungrounded_sets() -> None:
    first = _hypothesis(
        "one",
        state="active",
        side="intracellular",
        anchors="90,91",
        exclusions="3,7",
        directness="homolog_transfer",
    )
    duplicate = {**first, "hypothesis_id": "two", "target_source_id": "PDB:TWO"}
    duplicate_result = gpcr_hypothesis_portfolio(receptor_id="TEST", hypotheses=[first, duplicate])
    assert duplicate_result["error"] == "invalid_args"
    assert "duplicates" in duplicate_result["summary"]

    second = _hypothesis(
        "two",
        state="inactive",
        side="extracellular",
        anchors="3,7",
        exclusions="90,91",
        directness="homolog_transfer",
    )
    ungrounded_result = gpcr_hypothesis_portfolio(receptor_id="TEST", hypotheses=[first, second])
    assert ungrounded_result["error"] == "invalid_args"
    assert "direct same-receptor" in ungrounded_result["summary"]


def test_prepare_rejects_modeled_hotspots_and_portfolio_drift(tmp_path: Path, monkeypatch) -> None:
    path = _gpcr(tmp_path)
    modeled = _representation_kwargs("inactive")
    modeled["modeled_regions"] = "3-4"
    result = gpcr_target_prepare(
        target_pdb=str(path),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched extracellular epitope with resolved experimental anchors.",
        state_rationale="An antagonist-bound source supports the inactive state assignment.",
        **modeled,
    )
    assert result["error"] == "invalid_args"
    assert "modeled residues" in result["summary"]

    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda name, *_args: tmp_path / name,
    )
    (tmp_path / "gpcr_hypothesis_portfolio").mkdir()
    portfolio = gpcr_hypothesis_portfolio(
        receptor_id="TEST_RECEPTOR",
        hypotheses=[
            _hypothesis(
                "active-intracellular",
                state="active",
                side="intracellular",
                anchors="90,91",
                exclusions="3,7",
                directness="direct_same_receptor",
            ),
            _hypothesis(
                "inactive-extracellular",
                state="inactive",
                side="extracellular",
                anchors="3,7,12",
                exclusions="90,91",
                directness="homolog_transfer",
            ),
        ],
    )
    linked = _representation_kwargs("inactive")
    linked["hypothesis_id"] = "inactive-extracellular"
    linked["hypothesis_portfolio_path"] = portfolio["hypothesis_portfolio_path"]
    drift = gpcr_target_prepare(
        target_pdb=str(path),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched extracellular epitope with resolved experimental anchors.",
        state_rationale="An antagonist-bound source supports the inactive state assignment.",
        **linked,
    )
    assert drift["error"] == "invalid_args"
    assert "disagrees with portfolio" in drift["summary"]


def test_prepare_flags_sequence_only_state_loss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "proteinclaw.tools.gpcr_target.tool_output_dir",
        lambda *_args: tmp_path / "state-loss",
    )
    (tmp_path / "state-loss").mkdir()
    path = _gpcr(tmp_path)
    context = _representation_kwargs("inactive")
    context["confirmation_strategy"] = "sequence_only_state_uncontrolled"
    context["counterstate_source_ids"] = []
    result = gpcr_target_prepare(
        target_pdb=str(path),
        target_mmcif=str(_gpcr_mmcif(tmp_path, path)),
        target_chain="R",
        binding_side="extracellular",
        receptor_state="inactive",
        binding_residues="3,7,12",
        excluded_residues="90,91",
        membrane_spans="14-16,24-26,34-36,44-46,54-56,64-66,74-76",
        epitope_rationale="A researched extracellular epitope with resolved experimental anchors.",
        state_rationale="An antagonist-bound source supports the inactive state assignment.",
        **context,
    )

    assert "error" not in result
    representation = result["target_representation"]
    assert representation["confirmation_state_preserved"] is False
    assert any("Sequence-only confirmation" in warning for warning in representation["warnings"])
    assert any("counterstate" in warning for warning in representation["warnings"])

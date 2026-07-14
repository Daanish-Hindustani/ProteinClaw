from __future__ import annotations

import json
import importlib
from pathlib import Path

import numpy as np

from proteinclaw.tools import registry
from proteinclaw.tools.gpcr_candidate_qc import (
    _cdr_ranges_from_design_mask,
    gpcr_candidate_qc,
    gpcr_confirmation_gate,
)

qc_module = importlib.import_module("proteinclaw.tools.gpcr_candidate_qc")


def _atom(serial: int, chain: str, residue: int, x: float, y: float = 0.0) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{y:8.3f}{0.0:8.3f}  1.00 80.00           C"
    )


def test_registered() -> None:
    assert registry.has_tool("analysis.gpcr_candidate_qc")
    assert registry.has_tool("analysis.gpcr_confirmation_gate")


def test_qc_rejects_forbidden_face_contact(tmp_path: Path) -> None:
    complex_path = tmp_path / "complex.pdb"
    complex_path.write_text(
        "\n".join(
            [
                _atom(1, "A", 3, 0.0),
                _atom(2, "A", 7, 2.0),
                _atom(3, "A", 18, 4.0),
                _atom(4, "A", 19, 20.0),
                _atom(5, "B", 1, 0.5, 1.0),
                _atom(6, "B", 2, 2.5, 1.0),
                "END",
            ]
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "target_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mapping_verified": True,
                "binding_residues_label": [3, 7],
                "excluded_residues_label": [18, 19],
            }
        ),
        encoding="utf-8",
    )

    result = gpcr_candidate_qc(
        complex_path=str(complex_path),
        target_manifest_path=str(manifest),
        min_bsa=0,
        max_bsa=10000,
        max_clash_score=10000,
        cdr_ranges='{"cdr1":[1,1],"cdr2":[1,1],"cdr3":[2,2]}',
    )

    assert result["passes_strict_gate"] is False
    assert result["forbidden_contact_residues"] == [18]
    assert "contacts forbidden" in result["gate_failures"][-1]


def test_qc_maps_boltz_prediction_sequence_back_to_author_numbering(
    tmp_path: Path, monkeypatch
) -> None:
    prepared = tmp_path / "prepared_gpcr.pdb"
    prepared.write_text(
        "\n".join(
            [
                _atom(1, "A", 100, 0.0),
                _atom(2, "A", 101, 1.0),
                _atom(3, "A", 102, 2.0),
                _atom(4, "A", 190, 3.0),
                _atom(5, "A", 191, 4.0),
                "END",
            ]
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "target_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "mapping_verified": True,
                "target_auth_chain": "A",
                "prepared_pdb_path": str(prepared),
                "binding_residues_author": [100, 102],
                "excluded_residues_author": [190, 191],
                "binding_residues_label": [900, 902],
                "excluded_residues_label": [990, 991],
            }
        ),
        encoding="utf-8",
    )

    def fake_metrics(*_args, **kwargs):
        assert kwargs["hotspots"] == [1, 3]
        return _mock_metrics(
            interface_residue_ids_target=[1, 3, 4],
            hotspot_satisfaction=1.0,
            hotspot_detail=[
                {"hotspot": str(value), "mapped_resnum": value, "satisfied": True}
                for value in (1, 3)
            ],
        )

    monkeypatch.setattr(qc_module, "compute_interface_metrics", fake_metrics)
    result = gpcr_candidate_qc(
        complex_path=str(tmp_path / "candidate.cif"),
        target_manifest_path=str(manifest),
        target_numbering="prediction_sequence",
        cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
    )

    assert result["target_numbering"] == "prediction_sequence"
    assert result["forbidden_contact_residues"] == [4]
    assert result["forbidden_contact_residues_author"] == [190]


def test_design_mask_derives_scaffold_specific_cdr_ranges(tmp_path: Path) -> None:
    complex_path = tmp_path / "complex.pdb"
    lines = [_atom(index, "A", index, float(index)) for index in range(1, 3)]
    lines += [_atom(10 + index, "B", index, float(index)) for index in range(1, 7)]
    complex_path.write_text("\n".join([*lines, "END"]), encoding="utf-8")
    mask_path = tmp_path / "design.npz"
    np.savez(mask_path, design_mask=np.array([0, 0, 1, 0, 1, 0, 1, 0], dtype=float))

    ranges = _cdr_ranges_from_design_mask(
        str(complex_path),
        str(mask_path),
        binder_chain="B",
        target_chain="A",
    )

    assert ranges == {"cdr1": [1, 1], "cdr2": [3, 3], "cdr3": [5, 5]}


def _write_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mapping_verified": True,
                "binding_residues_label": [10, 20, 30],
                "excluded_residues_label": [90, 91],
            }
        ),
        encoding="utf-8",
    )
    return path


def _mock_metrics(**updates):
    metrics = {
        "summary": "mock",
        "interface_contacts": 30,
        "interface_residues_binder": 15,
        "interface_residues_target": 15,
        "interface_residue_ids_binder": list(range(1, 16)),
        "interface_residue_ids_target": [10, 20, 30],
        "interface_bsa": 2200.0,
        "clash_score": 2.5,
        "n_clashes": 4,
        "contact_geometry": {"n_res_binder": 15, "n_res_target": 15, "com_distance": 7.0},
        "hotspot_satisfaction": 1.0,
        "hotspot_detail": [
            {"hotspot": str(value), "mapped_resnum": value, "satisfied": True}
            for value in (10, 20, 30)
        ],
        "interface_plddt": 0.82,
        "h3_plddt": 0.80,
        "cdr_contact_fraction": 0.8,
        "notes": [],
    }
    metrics.update(updates)
    return metrics


def test_qc_rejects_mor_false_positive_signature(tmp_path: Path, monkeypatch) -> None:
    """High hotspot/BSA/CDR values cannot hide weak confidence and clashes.

    Values reproduce the failure mode in mor_nanobody_campaign_v2/round1_qc.json.
    """
    monkeypatch.setattr(
        qc_module,
        "compute_interface_metrics",
        lambda *args, **kwargs: _mock_metrics(
            interface_bsa=2298.5,
            clash_score=10.14,
            interface_plddt=0.59,
            h3_plddt=0.56,
            cdr_contact_fraction=0.741,
        ),
    )

    result = gpcr_candidate_qc(
        complex_path=str(tmp_path / "candidate.cif"),
        target_manifest_path=str(_write_manifest(tmp_path)),
        cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
    )

    assert result["passes_strict_gate"] is False
    assert result["eligible_for_afm_confirmation"] is False
    assert "excessive interfacial clashes" in result["gate_failures"]
    assert "low or missing interface confidence" in result["gate_failures"]
    assert "low or missing CDR3 confidence" in result["gate_failures"]


def test_qc_rejects_incompletely_mapped_hotspot_set(tmp_path: Path, monkeypatch) -> None:
    metrics = _mock_metrics()
    metrics["hotspot_detail"][1]["satisfied"] = None
    monkeypatch.setattr(qc_module, "compute_interface_metrics", lambda *args, **kwargs: metrics)

    result = gpcr_candidate_qc(
        complex_path=str(tmp_path / "candidate.cif"),
        target_manifest_path=str(_write_manifest(tmp_path)),
        cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
    )

    assert result["mapped_hotspot_fraction"] == 0.667
    assert "incomplete intended-hotspot mapping" in result["gate_failures"]


def test_reference_calibrates_bsa_and_clash_bounds(tmp_path: Path, monkeypatch) -> None:
    calls = iter(
        [
            _mock_metrics(interface_bsa=2400.0, clash_score=5.5),
            _mock_metrics(interface_bsa=2000.0, clash_score=1.0),
        ]
    )
    monkeypatch.setattr(qc_module, "compute_interface_metrics", lambda *args, **kwargs: next(calls))

    result = gpcr_candidate_qc(
        complex_path=str(tmp_path / "candidate.cif"),
        target_manifest_path=str(_write_manifest(tmp_path)),
        cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
        reference_complex_path=str(tmp_path / "reference.cif"),
        max_clash_score=20.0,
    )

    assert result["gate_thresholds"]["min_bsa"] == 1300.0
    assert result["gate_thresholds"]["max_bsa"] == 2700.0
    assert result["gate_thresholds"]["max_clash_score"] == 4.0
    assert "excessive interfacial clashes" in result["gate_failures"]


def test_pose_refinement_can_pass_geometry_but_not_strict_confidence(
    tmp_path: Path, monkeypatch
) -> None:
    calls = iter(
        [
            _mock_metrics(
                cdr_contact_fraction=0.56,
                interface_plddt=0.0,
                h3_plddt=0.0,
            ),
            _mock_metrics(cdr_contact_fraction=0.58),
        ]
    )
    monkeypatch.setattr(qc_module, "compute_interface_metrics", lambda *args, **kwargs: next(calls))

    result = gpcr_candidate_qc(
        complex_path=str(tmp_path / "candidate.pdb"),
        target_manifest_path=str(_write_manifest(tmp_path)),
        cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
        reference_complex_path=str(tmp_path / "reference.cif"),
        reference_cdr_ranges='{"cdr1":[1,5],"cdr2":[6,10],"cdr3":[11,15]}',
        confidence_policy="external_confirmation",
    )

    assert result["passes_geometry_gate"] is True
    assert result["passes_strict_gate"] is False
    assert result["eligible_for_afm_confirmation"] is True
    assert result["gate_thresholds"]["min_cdr_contact_fraction"] == 0.53
    assert result["interface_confidence"] is None


def _write_confirmation_evidence(tmp_path: Path, *, weak: bool = False) -> tuple[Path, Path, Path]:
    candidate = {
        "num_models_scored": 1 if weak else 5,
        "missing_score_json_pdbs": [],
        "avg_metrics": {"iptm": 0.72, "avg_interface_plddt": 90.0, "avg_interface_pae": 6.0},
        "avg_model_support": 4.0,
        "contact_reproducibility": 0.8,
        "mean_pairwise_contact_jaccard": 0.6,
        "iptm_stddev": 0.03,
        "combo_feature": 0.20,
    }
    control = {
        "num_models_scored": 5,
        "missing_score_json_pdbs": [],
        "avg_metrics": {"iptm": 0.67 if weak else 0.48, "avg_interface_plddt": 75.0, "avg_interface_pae": 7.0 if weak else 14.0},
        "avg_model_support": 2.0,
        "contact_reproducibility": 0.2,
        "mean_pairwise_contact_jaccard": 0.1,
        "iptm_stddev": 0.08,
        "combo_feature": 0.18 if weak else 0.10,
    }
    qc = {"passes_strict_gate": True}
    paths = (tmp_path / "candidate.json", tmp_path / "control.json", tmp_path / "qc.json")
    for path, payload in zip(paths, (candidate, control, qc), strict=True):
        path.write_text(json.dumps(payload), encoding="utf-8")
    return paths


def test_confirmation_gate_requires_reproducible_control_separation(tmp_path: Path) -> None:
    candidate, control, qc = _write_confirmation_evidence(tmp_path)

    result = gpcr_confirmation_gate(
        candidate_afm_score_path=str(candidate),
        negative_control_afm_score_path=str(control),
        candidate_qc_path=str(qc),
    )

    assert result["passes_confirmation_gate"] is True
    assert result["control_margins"]["iptm"] == 0.24
    assert result["control_margins"]["interface_pae"] == 8.0


def test_confirmation_gate_rejects_one_model_and_control_tie(tmp_path: Path) -> None:
    candidate, control, qc = _write_confirmation_evidence(tmp_path, weak=True)

    result = gpcr_confirmation_gate(
        candidate_afm_score_path=str(candidate),
        negative_control_afm_score_path=str(control),
        candidate_qc_path=str(qc),
    )

    assert result["passes_confirmation_gate"] is False
    assert "candidate has fewer than 5 scored AF-M models" in result["gate_failures"]
    assert "candidate does not separate from control by AF-M ipTM" in result["gate_failures"]
    assert "candidate does not separate from control by composite score" in result["gate_failures"]

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import json

from proteinclaw.tools.boltzgen_nanobody.implementation import (
    _design_spec,
    _validate_custom_scaffold,
    run,
)


def _redesign_manifest(target: Path, reference_id: str = "PDB:5C1M/Nb39") -> dict:
    return {
        "schema_version": 3,
        "prepared_mmcif_path": str(target),
        "target_label_chain": "R",
        "binding_residues_label": [3, 7],
        "excluded_residues_label": [18, 19],
        "mapping_verified": True,
        "topology_verified": True,
        "full_chain_preserved": True,
        "target_representation": {"reference_scaffold_ids": [reference_id]},
    }


def _custom_scaffold_files(tmp_path: Path) -> tuple[Path, Path]:
    coordinate = tmp_path / "nb39.cif"
    coordinate.write_text(
        "data_nb39\nloop_\n_atom_site.group_PDB\n_atom_site.id\nATOM 1\n",
        encoding="utf-8",
    )
    spec = tmp_path / "nb39.yaml"
    spec.write_text(
        json.dumps(
            {
                "path": "nb39.cif",
                "include": [{"chain": {"id": "B"}}],
                "design": [{"chain": {"id": "B", "res_index": "52..59,72..75"}}],
                "structure_groups": [
                    {"group": {"id": "B", "visibility": 2}},
                    {
                        "group": {
                            "id": "B",
                            "visibility": 0,
                            "res_index": "52..59,72..75",
                        }
                    },
                ],
                "reset_res_index": [{"chain": {"id": "B"}}],
            }
        ),
        encoding="utf-8",
    )
    return spec, coordinate


def test_design_spec_keeps_full_target_and_scaffold_candidates(tmp_path: Path) -> None:
    target = tmp_path / "prepared_gpcr.cif"
    spec = _design_spec(target, "R", [3, 7, 12], [18, 19])
    target_entity = spec["entities"][0]
    assert target_entity["file"]["path"] == str(target)
    assert target_entity["file"]["include"] == [{"chain": {"id": "R"}}]
    assert target_entity["file"]["binding_types"][0]["chain"]["binding"] == "3,7,12"
    assert target_entity["file"]["binding_types"][0]["chain"]["not_binding"] == "18,19"
    scaffold_paths = spec["entities"][1]["file"]["path"]
    assert len(scaffold_paths) >= 4
    assert all(isinstance(path, str) for path in scaffold_paths)


def test_run_rejects_unverified_numbering_before_generation(tmp_path: Path) -> None:
    target = tmp_path / "prepared_gpcr.cif"
    target.write_text("data_test\n", encoding="utf-8")
    manifest_path = tmp_path / "target_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "prepared_mmcif_path": str(target),
                "target_label_chain": "R",
                "binding_residues_label": [3, 7],
                "excluded_residues_label": [18, 19],
                "mapping_verified": False,
                "topology_verified": True,
                "full_chain_preserved": True,
            }
        ),
        encoding="utf-8",
    )

    result = run(target_manifest_path=str(manifest_path), num_designs=4, budget=1)

    assert result["error"] == "invalid_args"
    assert "mapping" in result["summary"]


def test_custom_scaffold_validation_links_manifest_provenance(tmp_path: Path) -> None:
    target = tmp_path / "target.cif"
    target.write_text("data_target\n", encoding="utf-8")
    spec, coordinate = _custom_scaffold_files(tmp_path)

    validated_spec, validated_coordinate, payload = _validate_custom_scaffold(
        scaffold_spec_path=str(spec),
        scaffold_structure_path=str(coordinate),
        scaffold_reference_id="pdb:5c1m/nb39",
        manifest=_redesign_manifest(target),
        workspace_root=tmp_path,
    )

    assert validated_spec == spec
    assert validated_coordinate == coordinate
    assert payload["design"][0]["chain"]["res_index"] == "52..59,72..75"


def test_custom_scaffold_rejects_path_outside_workspace(tmp_path: Path) -> None:
    target = tmp_path / "target.cif"
    target.write_text("data_target\n", encoding="utf-8")
    spec, _ = _custom_scaffold_files(tmp_path)
    outside = tmp_path.parent / "outside_nb39.cif"
    outside.write_text("data_nb39\n_atom_site.id\nATOM 1\n", encoding="utf-8")

    try:
        _validate_custom_scaffold(
            scaffold_spec_path=str(spec),
            scaffold_structure_path=str(outside),
            scaffold_reference_id="PDB:5C1M/Nb39",
            manifest=_redesign_manifest(target),
            workspace_root=tmp_path,
        )
    except ValueError as exc:
        assert "must live under" in str(exc)
    else:  # pragma: no cover - a fail-open path would be a security/science bug
        raise AssertionError("outside-workspace scaffold was accepted")


def test_custom_scaffold_rejects_reference_not_declared_in_manifest(tmp_path: Path) -> None:
    target = tmp_path / "target.cif"
    target.write_text("data_target\n", encoding="utf-8")
    spec, coordinate = _custom_scaffold_files(tmp_path)

    try:
        _validate_custom_scaffold(
            scaffold_spec_path=str(spec),
            scaffold_structure_path=str(coordinate),
            scaffold_reference_id="PDB:8QOT/NbE",
            manifest=_redesign_manifest(target),
            workspace_root=tmp_path,
        )
    except ValueError as exc:
        assert "reference_scaffold_ids" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unrecorded scaffold provenance was accepted")


def test_run_scaffold_redesign_stages_one_custom_scaffold(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "prepared_gpcr.cif"
    target.write_text("data_target\n", encoding="utf-8")
    manifest_path = tmp_path / "target_manifest.json"
    manifest_path.write_text(json.dumps(_redesign_manifest(target)), encoding="utf-8")
    spec, coordinate = _custom_scaffold_files(tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "proteinclaw.tools.boltzgen_nanobody.implementation.subprocess.run",
        fake_run,
    )

    result = run(
        target_manifest_path=str(manifest_path),
        num_designs=4,
        budget=1,
        design_mode="scaffold_redesign",
        scaffold_spec_path=str(spec),
        scaffold_structure_path=str(coordinate),
        scaffold_reference_id="PDB:5C1M/Nb39",
        _workspace_root=str(tmp_path),
    )

    assert "error" not in result
    assert result["design_mode"] == "scaffold_redesign"
    assert result["protocol"] == "nanobody-anything"
    assert result["scaffold_reference_id"] == "PDB:5C1M/Nb39"
    assert len(result["scaffold_spec_sha256"]) == 64
    assert len(result["scaffold_structure_sha256"]) == 64
    generated = json.loads(
        (tmp_path / "boltzgen_nanobody_0" / "design_spec.yaml").read_text(encoding="utf-8")
    )
    scaffold_paths = generated["entities"][1]["file"]["path"]
    assert scaffold_paths == [result["scaffold_spec_path"]]
    staged_payload = json.loads(Path(result["scaffold_spec_path"]).read_text(encoding="utf-8"))
    assert staged_payload["path"] == result["scaffold_structure_path"]
    assert calls[0][:2] == ["boltzgen", "check"]
    assert "nanobody-anything" in calls[1]

    coordinate.write_text(
        "data_changed\nloop_\n_atom_site.group_PDB\n_atom_site.id\nATOM 1\n",
        encoding="utf-8",
    )
    changed = run(
        target_manifest_path=str(manifest_path),
        num_designs=4,
        budget=1,
        design_mode="scaffold_redesign",
        scaffold_spec_path=str(spec),
        scaffold_structure_path=str(coordinate),
        scaffold_reference_id="PDB:5C1M/Nb39",
        _workspace_root=str(tmp_path),
    )
    assert changed["error"] == "invalid_args"
    assert "inputs changed" in changed["summary"]


def test_run_de_novo_rejects_custom_scaffold_inputs(tmp_path: Path) -> None:
    result = run(
        target_manifest_path=str(tmp_path / "missing.json"),
        design_mode="de_novo",
        scaffold_spec_path="nb39.yaml",
    )

    assert result["error"] == "invalid_args"
    assert "require design_mode='scaffold_redesign'" in result["summary"]

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.tools.boltz2_gpcr.implementation import (
    _input_payload,
    _parse_pdb_chain,
    run,
)


def _pdb_atom(serial: int, residue: str, chain: str, resid: int) -> str:
    return (
        f"ATOM  {serial:5d}  CA  {residue:>3s} {chain}{resid:4d}    "
        f"{float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 80.00           C  \n"
    )


def test_parse_pdb_chain_preserves_resolved_author_order(tmp_path: Path) -> None:
    pdb = tmp_path / "target.pdb"
    pdb.write_text(
        _pdb_atom(1, "ALA", "R", 67)
        + _pdb_atom(2, "GLY", "R", 68)
        + _pdb_atom(3, "TYR", "R", 70),
        encoding="utf-8",
    )

    sequence, author_resids = _parse_pdb_chain(pdb, "R")

    assert sequence == "AGY"
    assert author_resids == [67, 68, 70]


def test_input_payload_templates_only_receptor_and_maps_pocket(tmp_path: Path) -> None:
    payload = _input_payload(
        target_sequence="ACDE",
        binder_sequence="G" * 100,
        template_path=tmp_path / "target.pdb",
        template_chain="R",
        anchor_indices=[2, 4],
        use_msa_server=False,
        force_template=True,
        template_threshold=1.5,
        force_pocket=False,
    )

    assert payload["sequences"][0]["protein"]["msa"] == "empty"
    assert payload["templates"] == [
        {
            "cif": str(tmp_path / "target.pdb"),
            "chain_id": "A",
            "template_id": "R",
            "force": True,
            "threshold": 1.5,
        }
    ]
    assert payload["constraints"][0]["pocket"]["contacts"] == [["A", 2], ["A", 4]]
    assert payload["constraints"][0]["pocket"]["force"] is False


def test_run_rejects_manifest_without_state_preserving_confirmation(tmp_path: Path) -> None:
    pdb = tmp_path / "prepared_gpcr.pdb"
    pdb.write_text(
        _pdb_atom(1, "ALA", "R", 67) + _pdb_atom(2, "GLY", "R", 68),
        encoding="utf-8",
    )
    manifest = tmp_path / "target_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "mapping_verified": True,
                "topology_verified": True,
                "full_chain_preserved": True,
                "target_auth_chain": "R",
                "binding_residues_author": [67, 68],
                "prepared_pdb_path": str(pdb),
                "target_representation": {"confirmation_state_preserved": False},
            }
        ),
        encoding="utf-8",
    )

    result = run(
        target_manifest_path=str(manifest),
        binder_sequence="A" * 100,
        _workspace_root=str(tmp_path),
    )

    assert result["error"] == "invalid_args"
    assert "state-preserving" in result["summary"]

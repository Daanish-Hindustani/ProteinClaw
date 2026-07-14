from __future__ import annotations

import importlib.util
from pathlib import Path

from Bio.PDB import PDBParser

from proteinclaw.tools import registry
from proteinclaw.tools._container_tools import parse_manifest


def _load_implementation():
    path = Path(__file__).parents[2] / "src/proteinclaw/tools/gpcr_pose_refine/implementation.py"
    spec = importlib.util.spec_from_file_location("gpcr_pose_refine_impl", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _atom(serial: int, atom: str, chain: str, residue: int, x: float, y: float, z: float) -> str:
    return (
        f"ATOM  {serial:5d} {atom:^4s} ALA {chain}{residue:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 80.00           C"
    )


def _write_complex(path: Path, *, target_shift: float, include_binder: bool) -> None:
    lines: list[str] = []
    serial = 1
    for residue in range(1, 61):
        lines.append(_atom(serial, "CA", "A", residue, residue + target_shift, 0.0, 0.0))
        serial += 1
    if include_binder:
        for residue in range(1, 6):
            lines.append(_atom(serial, "CA", "B", residue, residue, 10.0, 0.0))
            serial += 1
    path.write_text("\n".join([*lines, "END"]), encoding="utf-8")


def test_registered_and_manifest_valid() -> None:
    assert registry.has_tool("structure.gpcr_pose_refine")
    path = Path(__file__).parents[2] / "src/proteinclaw/tools/gpcr_pose_refine/tool.yaml"
    tool = parse_manifest(path)
    assert tool.docker_image == "proteinclaw/gpcr-pose-refine:openmm-8.5.2"


def test_pose_transfer_aligns_target_and_moves_binder(tmp_path: Path) -> None:
    module = _load_implementation()
    target = tmp_path / "target.pdb"
    reference = tmp_path / "reference.pdb"
    output = tmp_path / "transferred.pdb"
    _write_complex(target, target_shift=5.0, include_binder=False)
    _write_complex(reference, target_shift=0.0, include_binder=True)

    result = module._build_pose_transfer(
        target_path=target,
        target_chain_id="A",
        reference_path=reference,
        reference_target_chain="A",
        reference_binder_chain="B",
        membrane_spans=[[1, 60]],
        max_alignment_rmsd=3.0,
        output_path=output,
    )

    model = PDBParser(QUIET=True).get_structure("out", output)[0]
    assert result["alignment_ca_atoms"] == 60
    assert result["alignment_rmsd_angstrom"] == 0.0
    assert result["receptor_sequence_identity"] == 1.0
    assert round(model["B"][1]["CA"].coord[0], 3) == 6.0

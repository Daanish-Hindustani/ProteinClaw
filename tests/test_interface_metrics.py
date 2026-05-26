"""Deterministic interface metrics (analysis.compute_interface_metrics).

Uses an inline synthetic 2-chain PDB with controlled coordinates for exact
assertions (no dependency on untracked run artifacts), plus a skip-if-absent
realism check against a staged AF2 complex when one exists locally.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from proteinclaw.analysis import (
    InterfaceMetricsError,
    compute_interface_metrics,
    parse_hotspots,
)


def _atom(serial, name, resname, chain, resseq, x, y, z, element):
    # Exact PDB columns: name 13-16, altLoc 17, resName 18-20, chain 22, resSeq 23-26.
    return (
        "ATOM  "
        f"{serial:>5} "
        f"{name:<4}"
        " "
        f"{resname:>3} "
        f"{chain:1}"
        f"{resseq:>4} "
        "   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}"
        "  1.00  0.00          "
        f"{element:>2}"
    )


def _residue(serial0, resname, chain, resseq, ca_xyz, cb_xyz):
    """A minimal residue: N, CA, C, O, CB around the given CA/CB coords."""
    cx, cy, cz = ca_xyz
    bx, by, bz = cb_xyz
    return [
        _atom(serial0 + 0, "N", resname, chain, resseq, cx - 1.0, cy, cz, "N"),
        _atom(serial0 + 1, "CA", resname, chain, resseq, cx, cy, cz, "C"),
        _atom(serial0 + 2, "C", resname, chain, resseq, cx + 1.0, cy, cz, "C"),
        _atom(serial0 + 3, "O", resname, chain, resseq, cx + 1.5, cy + 1.0, cz, "O"),
        _atom(serial0 + 4, "CB", resname, chain, resseq, bx, by, bz, "C"),
    ]


@pytest.fixture
def synthetic_complex(tmp_path: Path) -> str:
    """Chain A (binder) res 1-2, chain B (target) res 1-2.
    - A1.CB at (0,0,0) and B1.CB at (3.5,0,0): an inter-chain contact (≤4.5 Å).
    - A2.CB at (10,0,0) and B2.CB at (11.5,0,0): a 1.5 Å clash (C-C VdW 3.4 → <3.0).
    """
    lines = []
    s = 1
    for res in [
        _residue(s + 0, "ALA", "A", 1, (0, 0, 0), (0, 0, 0)),
        _residue(s + 5, "ALA", "A", 2, (10, 0, 0), (10, 0, 0)),
    ]:
        lines += res
    lines.append("TER")
    for res in [
        _residue(s + 10, "ALA", "B", 1, (3.5, 0, 0), (3.5, 0, 0)),
        _residue(s + 15, "ALA", "B", 2, (11.5, 0, 0), (11.5, 0, 0)),
    ]:
        lines += res
    lines.append("TER")
    p = tmp_path / "synthetic.pdb"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_parse_hotspots() -> None:
    assert parse_hotspots("A23,A107, A125") == ["A23", "A107", "A125"]
    assert parse_hotspots(["A23", "A107"]) == ["A23", "A107"]
    assert parse_hotspots("") == [] and parse_hotspots(None) == []


def test_synthetic_contacts_and_clash(synthetic_complex) -> None:
    m = compute_interface_metrics(synthetic_complex, binder_chain="A", target_chain="B")
    # A1↔B1 CB are 3.5 Å apart → at least one inter-chain residue contact.
    assert m["interface_contacts"] >= 1
    assert m["interface_residues_binder"] >= 1
    assert m["interface_residues_target"] >= 1
    # A2.CB↔B2.CB at 1.5 Å is a steric clash.
    assert m["n_clashes"] >= 1
    assert m["clash_score"] > 0
    # Two chains in contact bury some surface.
    assert m["interface_bsa"] > 0
    assert isinstance(m["interface_bsa"], float)


def test_synthetic_json_clean(synthetic_complex) -> None:
    """All metric values must be JSON-native (no numpy floats)."""
    import json

    m = compute_interface_metrics(synthetic_complex, hotspots="B1", crop_start=1)
    json.dumps(m)  # raises if a numpy float leaked through


def test_hotspot_crop_offset_mapping(synthetic_complex) -> None:
    # Target residues are 1 and 2. Hotspot "B6" with crop_start=6 → maps to 1.
    m = compute_interface_metrics(
        synthetic_complex, hotspots="B6", crop_start=6
    )
    assert m["hotspot_detail"][0]["mapped_resnum"] == 1
    assert m["hotspot_satisfaction"] is not None  # residue 1 exists + is contacted


def test_hotspot_unmapped_returns_none(synthetic_complex) -> None:
    # Hotspot maps to a residue not present → unmapped → satisfaction None + note.
    m = compute_interface_metrics(synthetic_complex, hotspots="B999", crop_start=1)
    assert m["hotspot_satisfaction"] is None
    assert any("mapped" in n for n in m["notes"])


def test_missing_file_raises() -> None:
    with pytest.raises(InterfaceMetricsError, match="not found"):
        compute_interface_metrics("/no/such/file.pdb")


def test_missing_chain_raises(synthetic_complex) -> None:
    with pytest.raises(InterfaceMetricsError, match="chain"):
        compute_interface_metrics(synthetic_complex, target_chain="Z")


@pytest.mark.skipif(
    not glob.glob("runs/*/designs/rank_01_*.pdb"),
    reason="no staged AF2 complex available locally",
)
def test_realism_against_staged_complex() -> None:
    pdb = sorted(glob.glob("runs/*/designs/rank_01_*.pdb"))[0]
    m = compute_interface_metrics(pdb, hotspots="A56,A115", crop_start=18)
    assert m["interface_contacts"] > 0
    assert m["interface_bsa"] > 200          # a real interface buries hundreds of Å²
    assert 0 <= m["clash_score"] < 200       # sane (designed structures run higher than crystals)
    assert m["contact_geometry"]["com_distance"] is not None

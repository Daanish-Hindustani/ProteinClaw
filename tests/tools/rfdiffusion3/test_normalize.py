"""RFD3 normalize_args + parsers — host-side tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_NORM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/proteinclaw/tools/rfdiffusion3/_normalize.py"
)
_spec = importlib.util.spec_from_file_location("_normalize_rfd3", _NORM_PATH)
_norm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_norm)  # type: ignore[union-attr]
NormalizeError = _norm.NormalizeError
parse_hotspot_residues = _norm.parse_hotspot_residues
parse_binder_length = _norm.parse_binder_length
parse_chain_ranges_and_resmap = _norm.parse_chain_ranges_and_resmap
default_atoms_for_residue = _norm.default_atoms_for_residue
build_hotspot_atom_map = _norm.build_hotspot_atom_map
build_input_spec = _norm.build_input_spec
normalize_args = _norm.normalize_args
normalize_partial_args = _norm.normalize_partial_args
chain_ca_counts = _norm.chain_ca_counts


_TINY_PDB = """\
HEADER    SYNTHETIC
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N
ATOM      2  CA  MET A   1      26.266  25.413   2.842  1.00 10.38           C
ATOM      3  CA  GLY A   2      27.000  24.000   2.000  1.00 11.00           C
ATOM      4  CA  TYR A  10      28.000  25.000   3.000  1.00 11.00           C
ATOM      5  CA  ALA B   1      29.000  26.000   4.000  1.00 12.00           C
END
"""


# --- hotspot + length parsers ---------------------------------------------


def test_hotspot_basic() -> None:
    assert parse_hotspot_residues("A56,A115,A123", "A") == ["A56", "A115", "A123"]


def test_hotspot_wrong_chain_rejected() -> None:
    with pytest.raises(NormalizeError, match="!= target_chain"):
        parse_hotspot_residues("A56,B115", "A")


def test_hotspot_garbage_rejected() -> None:
    with pytest.raises(NormalizeError):
        parse_hotspot_residues("not-a-token", "A")


def test_length_single_and_range() -> None:
    assert parse_binder_length("70") == (70, 70)
    assert parse_binder_length("60-90") == (60, 90)


def test_length_inverted_rejected() -> None:
    with pytest.raises(NormalizeError, match="lower bound"):
        parse_binder_length("90-60")


# --- chain-range + residue-type scanner -----------------------------------


def test_chain_ranges_and_types() -> None:
    ranges, types = parse_chain_ranges_and_resmap(_TINY_PDB)
    assert ranges == {"A": (1, 10), "B": (1, 1)}
    assert types[("A", 1)] == "MET"
    assert types[("A", 2)] == "GLY"
    assert types[("A", 10)] == "TYR"
    assert types[("B", 1)] == "ALA"


# --- atom-default selection -----------------------------------------------


def test_default_atoms_for_non_gly() -> None:
    assert default_atoms_for_residue("ALA") == "CA,CB"
    assert default_atoms_for_residue("TYR") == "CA,CB"
    assert default_atoms_for_residue("MET") == "CA,CB"


def test_default_atoms_for_gly() -> None:
    assert default_atoms_for_residue("GLY") == "CA"


def test_build_hotspot_atom_map_defaults() -> None:
    types = {("A", 1): "MET", ("A", 2): "GLY", ("A", 10): "TYR"}
    out = build_hotspot_atom_map(["A1", "A2", "A10"], types)
    assert out == {"A1": "CA,CB", "A2": "CA", "A10": "CA,CB"}


def test_build_hotspot_atom_map_overrides_win() -> None:
    types = {("A", 56): "TYR"}
    out = build_hotspot_atom_map(["A56"], types, overrides={"A56": "CG,OH"})
    assert out == {"A56": "CG,OH"}


# --- normalize_args end-to-end --------------------------------------------


def _ok(tmp_path: Path, **overrides):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    pdb = ws / "target.pdb"
    pdb.write_text(_TINY_PDB)
    base = dict(
        target_pdb=str(pdb),
        hotspot_residues="A1,A2,A10",
        workspace_root=str(ws),
    )
    base.update(overrides)
    return normalize_args(**base)


def test_normalize_defaults_apply_ppi_recommended(tmp_path: Path) -> None:
    args = _ok(tmp_path)
    assert args["step_scale"] == 3.0
    assert args["gamma_0"] == 0.2
    assert args["is_non_loopy"] is True
    assert args["select_hotspots"]["A2"] == "CA"  # Gly → CA only
    assert args["select_hotspots"]["A1"] == "CA,CB"


def test_normalize_step_scale_bounds(tmp_path: Path) -> None:
    with pytest.raises(NormalizeError, match="step_scale"):
        _ok(tmp_path, step_scale=10.0)


def test_normalize_gamma_0_bounds(tmp_path: Path) -> None:
    with pytest.raises(NormalizeError, match="gamma_0"):
        _ok(tmp_path, gamma_0=-0.1)


def test_normalize_hotspot_out_of_range(tmp_path: Path) -> None:
    with pytest.raises(NormalizeError, match="out of chain"):
        _ok(tmp_path, hotspot_residues="A999")


def test_normalize_hotspot_atoms_override(tmp_path: Path) -> None:
    args = _ok(
        tmp_path,
        hotspot_residues="A1,A10",
        hotspot_atoms={"A1": "CG,SD", "A10": "OH,CZ"},
    )
    assert args["select_hotspots"] == {"A1": "CG,SD", "A10": "OH,CZ"}


# --- build_input_spec produces the JSON RFD3 expects ----------------------


def test_build_input_spec_shape(tmp_path: Path) -> None:
    args = _ok(tmp_path, binder_length="60-70")
    spec = build_input_spec(args, spec_name="binder")
    assert "binder" in spec
    s = spec["binder"]
    assert s["dialect"] == 2
    assert s["infer_ori_strategy"] == "hotspots"
    assert s["contig"] == "60-70,/0,A1-10"
    assert s["select_hotspots"]["A2"] == "CA"
    assert s["is_non_loopy"] is True


# --- partial diffusion ----------------------------------------------------

# binder = chain A (3 CA), target = chain B (5 CA) — distinct sizes so the
# output classifier can tell them apart.
_COMPLEX_PDB = """\
HEADER    SYNTHETIC COMPLEX
ATOM      1  CA  MET A   1      27.340  24.430   2.614  1.00  9.67           C
ATOM      2  CA  GLY A   2      27.000  24.000   2.000  1.00 11.00           C
ATOM      3  CA  TYR A   3      28.000  25.000   3.000  1.00 11.00           C
ATOM      4  CA  ALA B   1      29.000  26.000   4.000  1.00 12.00           C
ATOM      5  CA  LEU B   2      30.000  27.000   5.000  1.00 12.00           C
ATOM      6  CA  VAL B   3      31.000  28.000   6.000  1.00 12.00           C
ATOM      7  CA  SER B   4      32.000  29.000   7.000  1.00 12.00           C
ATOM      8  CA  THR B   5      33.000  30.000   8.000  1.00 12.00           C
END
"""


def _write_complex(tmp_path: Path) -> Path:
    p = tmp_path / "prior_complex.pdb"
    p.write_text(_COMPLEX_PDB)
    return p


def test_chain_ca_counts() -> None:
    assert chain_ca_counts(_COMPLEX_PDB) == {"A": 3, "B": 5}


def test_partial_normalize_ok(tmp_path: Path) -> None:
    start = _write_complex(tmp_path)
    args = normalize_partial_args(
        start_pdb=str(start),
        partial_t=5.0,
        binder_chain="A",
        target_chain="B",
        workspace_root=str(tmp_path),
    )
    assert args["partial_t"] == 5.0
    assert args["start_pdb"] == str(start)
    assert args["binder_length"] == (3, 3)  # sized from binder chain A's CA count
    assert args["target_chain"] == "B"
    assert args["hotspot_residues"] == []
    assert "B" in args["chain_ranges"]


def test_partial_build_input_spec_no_contig(tmp_path: Path) -> None:
    start = _write_complex(tmp_path)
    args = normalize_partial_args(
        start_pdb=str(start), partial_t=7.5, workspace_root=str(tmp_path)
    )
    spec = build_input_spec(args, spec_name="binder")["binder"]
    assert spec["input"] == str(start)
    assert spec["partial_t"] == 7.5
    assert spec["dialect"] == 2
    assert "contig" not in spec  # partial diffusion forbids contig/length
    assert "select_hotspots" not in spec


@pytest.mark.parametrize("bad", [0, -1, 15.1, 20, "x"])
def test_partial_t_out_of_range_rejected(tmp_path: Path, bad: object) -> None:
    start = _write_complex(tmp_path)
    with pytest.raises(NormalizeError, match="partial_t"):
        normalize_partial_args(
            start_pdb=str(start), partial_t=bad, workspace_root=str(tmp_path)
        )


def test_partial_missing_start_pdb_rejected(tmp_path: Path) -> None:
    with pytest.raises(NormalizeError, match="start_pdb is required"):
        normalize_partial_args(
            start_pdb="", partial_t=5.0, workspace_root=str(tmp_path)
        )


def test_partial_start_pdb_outside_workspace_rejected(tmp_path: Path) -> None:
    start = _write_complex(tmp_path)
    with pytest.raises(NormalizeError, match="must live under"):
        normalize_partial_args(
            start_pdb=str(start), partial_t=5.0, workspace_root="/some/other/root"
        )


def test_partial_missing_chain_rejected(tmp_path: Path) -> None:
    start = _write_complex(tmp_path)
    with pytest.raises(NormalizeError, match="chain 'C' not in"):
        normalize_partial_args(
            start_pdb=str(start),
            partial_t=5.0,
            binder_chain="C",
            target_chain="B",
            workspace_root=str(tmp_path),
        )


def test_partial_same_chain_rejected(tmp_path: Path) -> None:
    start = _write_complex(tmp_path)
    with pytest.raises(NormalizeError, match="must differ"):
        normalize_partial_args(
            start_pdb=str(start),
            partial_t=5.0,
            binder_chain="A",
            target_chain="A",
            workspace_root=str(tmp_path),
        )

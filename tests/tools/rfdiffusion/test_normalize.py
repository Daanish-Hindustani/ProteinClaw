"""RFdiffusion normalize_args + parsers — host-side tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_NORM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/proteinclaw/tools/rfdiffusion/_normalize.py"
)
_spec = importlib.util.spec_from_file_location("_normalize_rfd", _NORM_PATH)
_normalize_rfd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_normalize_rfd)  # type: ignore[union-attr]
NormalizeError = _normalize_rfd.NormalizeError
parse_hotspot_residues = _normalize_rfd.parse_hotspot_residues
parse_binder_length = _normalize_rfd.parse_binder_length
parse_chain_ranges = _normalize_rfd.parse_chain_ranges
normalize_args = _normalize_rfd.normalize_args


_TINY_PDB = """\
HEADER    SYNTHETIC
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N
ATOM      2  CA  MET A   1      26.266  25.413   2.842  1.00 10.38           C
ATOM      3  N   ALA A  10      28.000  25.000   3.000  1.00 11.00           N
ATOM      4  N   GLY B   1      29.000  26.000   4.000  1.00 12.00           N
END
"""


# --- hotspot parser -------------------------------------------------------


def test_hotspot_basic() -> None:
    assert parse_hotspot_residues("A30,A33,A34", "A") == ["A30", "A33", "A34"]


def test_hotspot_strips_whitespace() -> None:
    assert parse_hotspot_residues(" A30 , A33 ", "A") == ["A30", "A33"]


def test_hotspot_case_insensitive_chain() -> None:
    assert parse_hotspot_residues("a30,a33", "A") == ["A30", "A33"]


def test_hotspot_missing_chain_rejected() -> None:
    with pytest.raises(NormalizeError, match="<chain><residue_number>"):
        parse_hotspot_residues("30,33", "A")


def test_hotspot_wrong_chain_rejected() -> None:
    with pytest.raises(NormalizeError, match="does not match target_chain"):
        parse_hotspot_residues("A30,B33", "A")


def test_hotspot_empty_rejected() -> None:
    with pytest.raises(NormalizeError, match="non-empty"):
        parse_hotspot_residues("", "A")


def test_hotspot_garbage_token_rejected() -> None:
    with pytest.raises(NormalizeError):
        parse_hotspot_residues("A30,not-a-token", "A")


# --- length parser --------------------------------------------------------


def test_length_single() -> None:
    assert parse_binder_length("70") == (70, 70)


def test_length_range() -> None:
    assert parse_binder_length("60-90") == (60, 90)


def test_length_inverted_rejected() -> None:
    with pytest.raises(NormalizeError, match="lower bound"):
        parse_binder_length("90-60")


def test_length_too_small_rejected() -> None:
    with pytest.raises(NormalizeError, match="5..500"):
        parse_binder_length("3")


def test_length_too_large_rejected() -> None:
    with pytest.raises(NormalizeError, match="5..500"):
        parse_binder_length("9999")


def test_length_garbage_rejected() -> None:
    with pytest.raises(NormalizeError):
        parse_binder_length("not-a-length")


# --- chain-range PDB scanner ----------------------------------------------


def test_parse_chain_ranges() -> None:
    r = parse_chain_ranges(_TINY_PDB)
    assert r == {"A": (1, 10), "B": (1, 1)}


def test_parse_chain_ranges_empty() -> None:
    assert parse_chain_ranges("") == {}


# --- normalize_args end-to-end --------------------------------------------


def _ok(**overrides):
    base = dict(
        target_pdb="/workspace/in.pdb",
        hotspot_residues="A30",
        skip_path_check=True,
    )
    base.update(overrides)
    return normalize_args(**base)


def test_normalize_defaults() -> None:
    args = _ok()
    assert args["binder_length"] == (70, 70)
    assert args["num_designs"] == 4
    assert args["diffuser_T"] == 50
    assert args["use_complex_weights"] is True
    assert args["target_chain"] == "A"


def test_normalize_hotspots_validated() -> None:
    with pytest.raises(NormalizeError):
        _ok(hotspot_residues="B30")  # wrong chain


def test_normalize_num_designs_bounds() -> None:
    with pytest.raises(NormalizeError, match="num_designs"):
        _ok(num_designs=0)
    with pytest.raises(NormalizeError, match="num_designs"):
        _ok(num_designs=33)


def test_normalize_diffuser_T_bounds() -> None:
    with pytest.raises(NormalizeError, match="diffuser_T"):
        _ok(diffuser_T=5)
    with pytest.raises(NormalizeError, match="diffuser_T"):
        _ok(diffuser_T=500)


def test_normalize_workspace_containment(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    pdb = ws / "target.pdb"
    pdb.write_text(_TINY_PDB)
    args = normalize_args(
        target_pdb=str(pdb),
        hotspot_residues="A1",
        workspace_root=str(ws),
        skip_path_check=False,
    )
    assert args["chain_ranges"] == {"A": (1, 10), "B": (1, 1)}


def test_normalize_hotspot_outside_chain_range_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    pdb = ws / "target.pdb"
    pdb.write_text(_TINY_PDB)
    with pytest.raises(NormalizeError, match="out of chain"):
        normalize_args(
            target_pdb=str(pdb),
            hotspot_residues="A999",
            workspace_root=str(ws),
            skip_path_check=False,
        )


def test_normalize_missing_target_chain_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    pdb = ws / "target.pdb"
    pdb.write_text(_TINY_PDB)
    with pytest.raises(NormalizeError, match="not found in PDB"):
        normalize_args(
            target_pdb=str(pdb),
            target_chain="Z",
            hotspot_residues="Z1",
            workspace_root=str(ws),
            skip_path_check=False,
        )

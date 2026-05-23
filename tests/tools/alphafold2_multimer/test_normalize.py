"""AF2-multimer normalize_args + per-chain pLDDT averaging — host tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_NORM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/proteinclaw/tools/alphafold2_multimer/_normalize.py"
)
_spec = importlib.util.spec_from_file_location("_normalize_af2", _NORM_PATH)
_normalize_af2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_normalize_af2)  # type: ignore[union-attr]
NormalizeError = _normalize_af2.NormalizeError
normalize_args = _normalize_af2.normalize_args
average_chain_plddt = _normalize_af2.average_chain_plddt


# Synthetic PDB with chain A (binder) at pLDDT 50, chain B (target) at 99.
# Tests our "binder-chain pLDDT averaging" against a known answer.
_PDB = """\
HEADER    AF2 MOCK
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00 50.00           N
ATOM      2  CA  MET A   1      26.266  25.413   2.842  1.00 50.00           C
ATOM      3  C   MET A   1      27.000  24.000   2.000  1.00 50.00           C
ATOM      4  CA  ALA A   2      28.000  25.000   3.000  1.00 50.00           C
ATOM      5  CA  GLY B   1      29.000  26.000   4.000  1.00 99.00           C
ATOM      6  CA  GLY B   2      30.000  27.000   5.000  1.00 99.00           C
END
"""


def _ok(**overrides):
    base = dict(
        binder_sequence="MEEPQSDPSV",
        target_sequence="MEEPQSDPSV",
    )
    base.update(overrides)
    return normalize_args(**base)


def test_basic_passes() -> None:
    args = _ok()
    assert args["msa_source"] == "colabfold"
    assert args["num_recycle"] == 3
    assert args["relax_prediction"] is False


def test_uppercase_normalisation() -> None:
    args = _ok(binder_sequence="meepqsdpsv")
    assert args["binder_sequence"] == "MEEPQSDPSV"


def test_too_short_rejected() -> None:
    with pytest.raises(NormalizeError, match="length must be"):
        _ok(binder_sequence="MEE")


def test_too_long_rejected() -> None:
    with pytest.raises(NormalizeError, match="length must be"):
        _ok(target_sequence="A" * 2000)


def test_ambiguity_residues_rejected_with_hint() -> None:
    with pytest.raises(NormalizeError, match="ambiguity code"):
        _ok(binder_sequence="MEXEPQSDPSV")


def test_non_aa_rejected() -> None:
    with pytest.raises(NormalizeError, match="non-standard"):
        _ok(binder_sequence="MEE3QSDPSV")


def test_msa_source_allowlist() -> None:
    _ok(msa_source="colabfold")
    _ok(msa_source="single_sequence")
    with pytest.raises(NormalizeError, match="msa_source"):
        _ok(msa_source="something_else")


def test_num_recycle_bounds() -> None:
    with pytest.raises(NormalizeError, match="num_recycle"):
        _ok(num_recycle=0)
    with pytest.raises(NormalizeError, match="num_recycle"):
        _ok(num_recycle=25)


def test_num_models_bounds() -> None:
    with pytest.raises(NormalizeError, match="num_models"):
        _ok(num_models=0)
    with pytest.raises(NormalizeError, match="num_models"):
        _ok(num_models=6)


# --- per-chain pLDDT averaging --------------------------------------------


def test_binder_chain_plddt_50() -> None:
    plddt, n = average_chain_plddt(_PDB, "A")
    assert n == 2  # only CA atoms count
    assert abs(plddt - 50.0) < 1e-9


def test_target_chain_plddt_99() -> None:
    plddt, n = average_chain_plddt(_PDB, "B")
    assert n == 2
    assert abs(plddt - 99.0) < 1e-9


def test_missing_chain_returns_zero() -> None:
    plddt, n = average_chain_plddt(_PDB, "Z")
    assert plddt == 0.0 and n == 0

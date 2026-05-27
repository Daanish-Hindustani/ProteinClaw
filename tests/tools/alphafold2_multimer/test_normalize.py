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
parse_ipsae_txt = _normalize_af2.parse_ipsae_txt


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


# --- ipSAE summary parsing -------------------------------------------------
# Real ipsae.py v4 output captured from a TREM2 binder+target complex
# (binder=A, target=B). Three rows: A->B asym, B->A asym, max.
_IPSAE_TXT = """\

Chn1 Chn2  PAE Dist  Type   ipSAE    ipSAE_d0chn ipSAE_d0dom  ipTM_af  ipTM_d0chn     pDockQ     pDockQ2    LIS       n0res  n0chn  n0dom   d0res   d0chn   d0dom  nres1   nres2   dist1   dist2  Model
A    B     10   10   asym  0.512798    0.634691    0.630233    0.720    0.622678      0.2951     0.4263     0.5360     115    193    189    3.96    5.18    5.12     74     115      39      31   complex_x
B    A     10   10   asym  0.433133    0.675837    0.665970    0.720    0.675837      0.2951     0.4245     0.5723      75    193    184    3.05    5.18    5.06    109      75      31      39   complex_x
A    B     10   10   max   0.512798    0.675837    0.665970    0.720    0.675837      0.2951     0.4263     0.5542     115    193    184    3.96    5.18    5.06     75     115      39      31   complex_x
"""


def test_parse_ipsae_uses_max_row() -> None:
    m = parse_ipsae_txt(_IPSAE_TXT, "A", "B")
    assert m["ipsae"] == 0.512798  # max over the two asym directions
    assert m["iptm"] == 0.720
    assert m["pdockq"] == 0.2951
    assert m["pdockq2"] == 0.4263
    assert m["lis"] == 0.5542


def test_parse_ipsae_chain_order_irrelevant() -> None:
    # The pair is a set — passing target/binder swapped finds the same row.
    assert parse_ipsae_txt(_IPSAE_TXT, "B", "A")["ipsae"] == 0.512798


def test_parse_ipsae_falls_back_to_asym_max_without_max_row() -> None:
    no_max = "\n".join(
        ln for ln in _IPSAE_TXT.splitlines() if "  max  " not in ln
    )
    m = parse_ipsae_txt(no_max, "A", "B")
    assert m["ipsae"] == 0.512798  # max(0.512798, 0.433133)


@pytest.mark.parametrize("bad", ["", "garbage with no table", "Chn1 ipSAE\n"])
def test_parse_ipsae_graceful_on_bad_input(bad: str) -> None:
    m = parse_ipsae_txt(bad, "A", "B")
    assert set(m) >= {"ipsae", "iptm", "pdockq", "pdockq2", "lis"}
    assert all(m[k] is None for k in ("ipsae", "iptm", "pdockq", "pdockq2", "lis"))


def test_parse_ipsae_missing_pair_returns_none() -> None:
    assert parse_ipsae_txt(_IPSAE_TXT, "C", "D")["ipsae"] is None


# --- ipSAE cutoff validation in normalize_args -----------------------------


def test_cutoffs_default_to_10() -> None:
    a = normalize_args(binder_sequence="ACDEFGHIK", target_sequence="ACDEFGHIKLMN")
    assert a["ipsae_pae_cutoff"] == 10.0
    assert a["ipsae_dist_cutoff"] == 10.0


def test_cutoffs_custom() -> None:
    a = normalize_args(
        binder_sequence="ACDEFGHIK",
        target_sequence="ACDEFGHIKLMN",
        ipsae_pae_cutoff=15,
        ipsae_dist_cutoff=8,
    )
    assert a["ipsae_pae_cutoff"] == 15.0 and a["ipsae_dist_cutoff"] == 8.0


@pytest.mark.parametrize("bad", [0, -1, 100, "x", True])
def test_cutoffs_reject_invalid(bad: object) -> None:
    with pytest.raises(NormalizeError):
        normalize_args(
            binder_sequence="ACDEFGHIK",
            target_sequence="ACDEFGHIKLMN",
            ipsae_pae_cutoff=bad,
        )

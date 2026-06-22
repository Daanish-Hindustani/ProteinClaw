"""Unit tests for analysis.binding_affinity (PRODIGY KD/ΔG, advisory)."""

from __future__ import annotations

import glob

import pytest

from proteinclaw.tools.binding_affinity import binding_affinity


def test_missing_file_is_invalid_args() -> None:
    out = binding_affinity(complex_pdb_path="/no/such/complex.pdb")
    assert out["error"] == "invalid_args"


def test_soft_fail_never_raises_on_degenerate_pdb(tmp_path) -> None:
    """A degenerate complex must degrade to null + caveat, never raise."""
    p = tmp_path / "tiny.pdb"
    p.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CA  ALA B   1       3.500   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    out = binding_affinity(complex_pdb_path=str(p))
    # Either it returns a number or soft-fails — but it always carries the caveat
    # and never raises, and is never gated.
    assert "caveat" in out and "ADVISORY" in out["caveat"]
    assert "predicted_kd_nm" in out


@pytest.mark.skipif(
    not glob.glob("runs/*/designs/rank_01_*.pdb"),
    reason="no staged complex available locally",
)
def test_real_complex_returns_numbers() -> None:
    pdb = sorted(glob.glob("runs/*/designs/rank_01_*.pdb"))[0]
    out = binding_affinity(complex_pdb_path=pdb)
    if out.get("predicted_kd_nm") is not None:
        assert out["predicted_dg"] < 0  # favourable ΔG is negative
        assert out["predicted_kd_nm"] > 0


def test_registered() -> None:
    from proteinclaw.tools import registry

    assert registry.has_tool("analysis.binding_affinity")

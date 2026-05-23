"""Task 6.2 — pdb_fetch unit tests (mocked) + live E2E."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools._paths import DEFAULT_CACHE_ROOT, DEFAULT_WORKSPACE_ROOT
from proteinclaw.tools.pdb import _filter_pdb, _parse_crop, pdb_fetch

# A tiny synthetic PDB with two chains and a residue range covering 1–10.
_TINY_PDB = """\
HEADER    SYNTHETIC                              01-JAN-26   TEST
TITLE     SYNTHETIC TEST STRUCTURE
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N
ATOM      2  CA  MET A   1      26.266  25.413   2.842  1.00 10.38           C
ATOM      3  N   MET A   2      27.000  24.000   2.000  1.00 10.00           N
ATOM      4  N   ALA A  10      28.000  25.000   3.000  1.00 11.00           N
ATOM      5  N   GLY B   1      29.000  26.000   4.000  1.00 12.00           N
ATOM      6  N   GLY B   2      30.000  27.000   5.000  1.00 13.00           N
TER       7      GLY B   2
END
"""


def test_registered() -> None:
    assert "data.pdb_fetch" in registry


def test_parse_crop_ok_and_bad() -> None:
    assert _parse_crop("10-20") == (10, 20)
    with pytest.raises(ValueError):
        _parse_crop("20-10")
    with pytest.raises(ValueError):
        _parse_crop("not-a-range")


def test_filter_chain_only() -> None:
    text, atoms, residues = _filter_pdb(_TINY_PDB, chain="A", crop=None)
    assert "GLY B" not in text
    assert atoms == 4 and residues == 3  # 4 ATOMs across resi {1, 2, 10} of chain A


def test_filter_chain_and_crop() -> None:
    text, atoms, residues = _filter_pdb(_TINY_PDB, chain="A", crop=(1, 2))
    assert "ALA A  10" not in text
    assert atoms == 3 and residues == 2


def test_filter_no_match() -> None:
    text, atoms, residues = _filter_pdb(_TINY_PDB, chain="Z", crop=None)
    assert atoms == 0 and residues == 0


def test_invalid_pdb_id_rejected() -> None:
    r = pdb_fetch(pdb_id="nope")
    assert r["error"] == "invalid_query"


def test_invalid_crop_rejected() -> None:
    r = pdb_fetch(pdb_id="1abc", crop="20-10")
    assert r["error"] == "invalid_query"


@responses.activate
def test_fetch_caches_and_returns_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("proteinclaw.tools.pdb.tool_cache_dir", lambda _: tmp_path)
    responses.add(
        responses.GET,
        "https://files.rcsb.org/download/1ABC.pdb",
        body=_TINY_PDB,
        status=200,
        content_type="text/plain",
    )
    r = pdb_fetch(pdb_id="1abc")
    assert r["pdb_id"] == "1ABC"
    assert Path(r["pdb_path"]).exists()
    # Second call should hit cache (no second HTTP call).
    r2 = pdb_fetch(pdb_id="1abc")
    assert r2["pdb_path"] == r["pdb_path"]
    # responses verifies that every registered URL was hit exactly once.
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_with_chain_writes_filtered_subpdb(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("proteinclaw.tools.pdb.tool_cache_dir", lambda _: tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    workspace = tmp_path / "workspace"

    def fake_output(tool_short, session_id, step):
        d = workspace / f"{tool_short}_{step}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("proteinclaw.tools.pdb.tool_output_dir", fake_output)
    responses.add(
        responses.GET,
        "https://files.rcsb.org/download/1ABC.pdb",
        body=_TINY_PDB,
        status=200,
        content_type="text/plain",
    )
    r = pdb_fetch(pdb_id="1abc", chain="A", crop="1-2", session_id="sess1")
    assert r["chain"] == "A" and r["crop"] == "1-2"
    cropped = Path(r["cropped_pdb_path"])
    assert cropped.exists()
    text = cropped.read_text()
    assert "MET A" in text and "GLY B" not in text
    assert "session_id" in r and r["session_id"] == "sess1"


@responses.activate
def test_fetch_404_returns_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("proteinclaw.tools.pdb.tool_cache_dir", lambda _: tmp_path)
    responses.add(
        responses.GET, "https://files.rcsb.org/download/9ZZZ.pdb", status=404
    )
    r = pdb_fetch(pdb_id="9zzz")
    assert r["error"] == "not_found"


@responses.activate
def test_fetch_with_chain_returning_no_atoms(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("proteinclaw.tools.pdb.tool_cache_dir", lambda _: tmp_path)
    responses.add(
        responses.GET,
        "https://files.rcsb.org/download/1ABC.pdb",
        body=_TINY_PDB,
        status=200,
        content_type="text/plain",
    )
    r = pdb_fetch(pdb_id="1abc", chain="Z")
    assert r["error"] == "empty_after_filter"


# --- Live E2E ---------------------------------------------------------------


@pytest.mark.live
def test_live_fetch_5jds_chain_A_crop() -> None:
    """5JDS = PD-L1 in complex; chain A crop ~18-134 covers the IgV domain."""
    r = pdb_fetch(pdb_id="5JDS", chain="A", crop="18-134", session_id="live-pdl1")
    assert r["pdb_id"] == "5JDS"
    assert Path(r["pdb_path"]).exists()
    assert Path(r["cropped_pdb_path"]).exists()
    assert r["num_atoms"] > 100
    # IgV is ~117 residues; allow some slack for missing densities.
    assert 80 < r["num_residues"] < 200

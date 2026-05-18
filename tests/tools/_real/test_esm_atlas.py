"""Tests for the ESM Atlas backend with httpx MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real.esm_atlas import (
    EsmAtlasBackend,
    _normalize_plddt_bfactor,
)
from proteinclaw.tools.protein.alphafold import FoldInputs


def _fake_pdb(plddt_per_residue: list[float]) -> str:
    """Build a minimal PDB whose CA B-factor column carries given pLDDT values."""
    lines = ["HEADER    fake"]
    for i, p in enumerate(plddt_per_residue, start=1):
        # PDB columns: ATOM(1-6), serial(7-11), name(13-16), altLoc(17),
        # resName(18-20), chainID(22), resSeq(23-26), iCode(27),
        # x(31-38), y(39-46), z(47-54), occupancy(55-60), tempFactor(61-66).
        lines.append(
            f"ATOM  {i:>5d}  CA  ALA A{i:>4d}    "
            f"{0.0:>8.3f}{0.0:>8.3f}{0.0:>8.3f}"
            f"{1.0:>6.2f}{p:>6.2f}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://api.esmatlas.com")


async def test_fold_happy_path(tmp_path: Path) -> None:
    pdb = _fake_pdb([90.0, 88.0, 92.0, 80.0])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, text=pdb)

    backend = EsmAtlasBackend(client=_client(httpx.MockTransport(handler)), output_dir=tmp_path)
    out = await backend.fold(FoldInputs(sequence="MKVLAVAGAATG"))
    assert Path(out.pdb_path).read_text() == pdb  # noqa: ASYNC240 — sync read in test
    # Mean of [90,88,92,80] / 100 = 0.875
    assert abs(out.plddt - 0.875) < 1e-6


def test_normalize_plddt_bfactor_accepts_fractional_and_percent_scales() -> None:
    assert _normalize_plddt_bfactor(0.875) == pytest.approx(0.875)
    assert _normalize_plddt_bfactor(87.5) == pytest.approx(0.875)
    assert _normalize_plddt_bfactor(150.0) == 1.0
    assert _normalize_plddt_bfactor(-0.2) == 0.0


async def test_fold_msa_rejected() -> None:
    backend = EsmAtlasBackend(client=httpx.AsyncClient())
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fold(FoldInputs(sequence="MKVLAVAGAATG", msa="some-msa"))
    assert "single-sequence" in str(ex.value)


async def test_fold_too_long_rejected() -> None:
    backend = EsmAtlasBackend(client=httpx.AsyncClient())
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fold(FoldInputs(sequence="A" * 401))
    assert "exceeds" in str(ex.value)


async def test_fold_5xx_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    backend = EsmAtlasBackend(client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fold(FoldInputs(sequence="MKVLAVAGAATG"))
    assert "503" in str(ex.value)


async def test_fold_non_pdb_response_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>error page</html>")

    backend = EsmAtlasBackend(client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fold(FoldInputs(sequence="MKVLAVAGAATG"))
    assert "not a PDB" in str(ex.value)

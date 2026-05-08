"""Tests for the real RCSB REST backend with httpx MockTransport."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real.rcsb_rest import RcsbRestBackend
from proteinclaw.tools.protein.rcsb import RCSBInputs


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://data.rcsb.org")


def _good_payload() -> dict[str, Any]:
    return {
        "entity_poly": {
            "pdbx_seq_one_letter_code_can": "MKVLAVAGAATG",
        },
        "rcsb_entity_source_organism": [{"scientific_name": "Homo sapiens"}],
    }


async def test_fetch_happy_path() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_good_payload())

    backend = RcsbRestBackend(client=_client(httpx.MockTransport(handler)))
    out = await backend.fetch(RCSBInputs(pdb_id="1abc"))
    assert out.pdb_id == "1ABC"  # uppercased by the schema validator
    assert out.sequence == "MKVLAVAGAATG"
    assert out.length == len(out.sequence)
    assert out.organism == "Homo sapiens"
    assert "1ABC" in str(captured[0].url)


async def test_fetch_404_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    backend = RcsbRestBackend(client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fetch(RCSBInputs(pdb_id="9ZZZ"))
    assert "not found" in str(ex.value).lower()


async def test_fetch_5xx_raises_with_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    backend = RcsbRestBackend(client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fetch(RCSBInputs(pdb_id="1ABC"))
    assert "503" in str(ex.value)


async def test_fetch_missing_sequence_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"entity_poly": {}}))

    backend = RcsbRestBackend(client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ToolExecutionError) as ex:
        await backend.fetch(RCSBInputs(pdb_id="1ABC"))
    assert "no canonical sequence" in str(ex.value)


async def test_organism_falls_back_to_unknown() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        body = _good_payload()
        body.pop("rcsb_entity_source_organism")
        return httpx.Response(200, json=body)

    backend = RcsbRestBackend(client=_client(httpx.MockTransport(handler)))
    out = await backend.fetch(RCSBInputs(pdb_id="1ABC"))
    assert out.organism == "unknown"

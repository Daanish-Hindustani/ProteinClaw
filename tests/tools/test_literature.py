"""Task 6.4 — literature_search unit tests + live E2E."""

from __future__ import annotations

import requests

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.literature import literature_search


def test_registered() -> None:
    assert "research.literature_search" in registry


@responses.activate
def test_basic_search_parses_results() -> None:
    responses.add(
        responses.GET,
        "https://api.semanticscholar.org/graph/v1/paper/search",
        json={
            "data": [
                {
                    "paperId": "abc123",
                    "title": "De novo design of PD-L1 binders",
                    "year": 2024,
                    "venue": "Nature",
                    "authors": [{"name": "X. Author"}, {"name": "Y. Author"}],
                    "url": "https://example.org/paper",
                    "abstract": "A " * 250,
                }
            ],
            "total": 1,
        },
        status=200,
    )
    r = literature_search(query="PD-L1 binder design")
    assert r["rate_limited"] is False
    assert len(r["results"]) == 1
    p = r["results"][0]
    assert p["title"].startswith("De novo")
    assert p["year"] == 2024
    assert len(p["abstract_preview"]) <= 401  # 400 + ellipsis


@responses.activate
def test_429_returns_rate_limited_envelope_not_error() -> None:
    responses.add(
        responses.GET,
        "https://api.semanticscholar.org/graph/v1/paper/search",
        status=429,
        body="rate limited",
    )
    r = literature_search(query="anything")
    assert r["rate_limited"] is True
    assert r["results"] == []
    # Critically: no "error" field set so the agent doesn't treat it as failure.
    assert "error" not in r


@responses.activate
def test_5xx_returns_empty_results_no_throw() -> None:
    responses.add(
        responses.GET,
        "https://api.semanticscholar.org/graph/v1/paper/search",
        status=503,
    )
    r = literature_search(query="anything")
    assert r["results"] == []
    assert r["rate_limited"] is False
    assert "error" not in r


def test_network_failure_does_not_raise(monkeypatch) -> None:
    class _FailingSession:
        headers: dict = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("dns boom")

    r = literature_search(query="x", session=_FailingSession())  # type: ignore[arg-type]
    assert r["results"] == []
    assert r["rate_limited"] is True


# --- Live E2E ---------------------------------------------------------------


@pytest.mark.live
def test_live_pdl1_binder_search() -> None:
    r = literature_search(query="PD-L1 binder design", limit=3)
    # Either results or a graceful rate-limit — both are acceptable outcomes.
    assert "results" in r
    if not r["rate_limited"]:
        assert isinstance(r["results"], list)

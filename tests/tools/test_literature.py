"""Single-query LitSense + PubMed fallback path for ``research.literature_search``."""

from __future__ import annotations

import requests

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.literature import (
    LITSENSE_URL,
    PUBMED_ESEARCH,
    PUBMED_ESUMMARY,
    literature_search,
)


def test_registered() -> None:
    assert "research.literature_search" in registry


# --- arg validation ---------------------------------------------------------


def test_invalid_args_when_no_query() -> None:
    r = literature_search(query=None)  # type: ignore[arg-type]
    assert r["error"] == "invalid_args"


def test_invalid_args_when_blank() -> None:
    r = literature_search(query="   ")
    assert r["error"] == "invalid_args"


# --- LitSense primary path --------------------------------------------------


@responses.activate
def test_litsense_passages_returned_in_score_order() -> None:
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json=[
            {"pmcid": "PMC1", "pmid": 1, "section": "INTRO",
             "text": "Lower scored sentence.", "score": 0.4},
            {"pmcid": "PMC2", "pmid": 2, "section": "RESULTS",
             "text": "Higher scored sentence.", "score": 0.9},
        ],
        status=200,
    )
    r = literature_search(query="PD-L1 binder")
    assert r["num_passages"] == 2
    assert r["passages"][0]["score"] == 0.9
    assert r["passages"][0]["section"] == "RESULTS"
    assert r["rate_limited"] is False
    assert r["source"] == "litsense"


@responses.activate
def test_litsense_below_min_score_dropped() -> None:
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json=[
            {"pmcid": "PMC1", "pmid": 1, "section": "INTRO",
             "text": "barely relevant", "score": 0.05},
        ],
        status=200,
    )
    r = literature_search(query="x", min_score=0.3, with_pubmed_fallback=False)
    assert r["passages"] == []


@responses.activate
def test_litsense_no_results_falls_back_to_pubmed() -> None:
    """When LitSense returns the {detail: ...} no-results dict, try PubMed."""
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json={"detail": "No sentences share at least 30% of words."},
        status=200,
    )
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": ["12345", "67890"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        PUBMED_ESUMMARY,
        json={
            "result": {
                "12345": {
                    "title": "Discovery paper",
                    "pubdate": "2024",
                    "authors": [{"name": "A. Author"}],
                },
                "67890": {
                    "title": "Followup paper",
                    "pubdate": "2025",
                    "authors": [{"name": "B. Author"}],
                },
            }
        },
        status=200,
    )
    r = literature_search(query="esoteric")
    assert r["num_papers"] >= 1
    assert r["source"] == "pubmed_fallback"
    assert all(p["source"] == "pubmed" for p in r["passages"])


@responses.activate
def test_litsense_429_marks_rate_limited_after_retries() -> None:
    """Persistent 429 (3 attempts) marks the query rate-limited."""
    for _ in range(3):
        responses.add(responses.GET, LITSENSE_URL, status=429, body="rate limited")
    r = literature_search(query="x", with_pubmed_fallback=False)
    assert r["rate_limited"] is True
    assert r["passages"] == []
    assert "rate-limited" in r["summary"].lower()


@responses.activate
def test_litsense_429_then_200_succeeds_via_retry() -> None:
    """Transient 429 followed by success returns passages (retry-with-backoff)."""
    responses.add(responses.GET, LITSENSE_URL, status=429, body="slow down")
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json=[
            {"pmcid": "PMC1", "pmid": 1, "section": "RESULTS",
             "text": "Recovered sentence.", "score": 0.8},
        ],
        status=200,
    )
    r = literature_search(query="x")
    assert r["rate_limited"] is False
    assert r["num_passages"] == 1


def test_network_failure_degrades_gracefully() -> None:
    class _FailingSession:
        headers: dict = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("dns boom")

    r = literature_search(query="x", session=_FailingSession())  # type: ignore[arg-type]
    assert r["passages"] == []
    assert r["rate_limited"] is True


# --- live --------------------------------------------------------------


@pytest.mark.live
def test_live_litsense_returns_passages() -> None:
    r = literature_search(query="PD-L1 binder design", limit=3)
    if not r["rate_limited"] and r["passages"]:
        p = r["passages"][0]
        assert "text" in p and "section" in p and "score" in p

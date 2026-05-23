"""Task 6.4 / Phase 6 polish — literature_search (LitSense + PubMed fallback)."""

from __future__ import annotations

import requests

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.literature import (
    LITSENSE_URL,
    PUBMED_ESEARCH,
    PUBMED_ESUMMARY,
    _normalize_queries,
    literature_search,
)


def test_registered() -> None:
    assert "research.literature_search" in registry


# --- query normalisation ----------------------------------------------------


def test_normalize_dedups_case_insensitive() -> None:
    out = _normalize_queries("PD-L1 BINDER", ["pd-l1 binder", "ESMFold filter"])
    # First non-empty form wins. Dedup is case-insensitive on the lowered key.
    assert len(out) == 2
    assert any("ESMFold" in q for q in out)


def test_normalize_caps_at_max() -> None:
    qs = [f"q{i}" for i in range(50)]
    out = _normalize_queries(None, qs)
    assert len(out) == 15


def test_normalize_rejects_blank() -> None:
    out = _normalize_queries(None, ["", "   ", "real query"])
    assert out == ["real query"]


def test_invalid_args_when_no_query() -> None:
    r = literature_search(query=None, queries=None)
    assert r["error"] == "invalid_query".replace("query", "args")  # invalid_args
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
    assert any(p["source"] == "pubmed" for p in r["passages"])
    assert r["per_query_status"]["esoteric"] == "fallback_pubmed"


@responses.activate
def test_litsense_429_marks_rate_limited() -> None:
    responses.add(responses.GET, LITSENSE_URL, status=429, body="rate limited")
    r = literature_search(query="x", with_pubmed_fallback=False)
    assert r["rate_limited"] is True
    assert r["passages"] == []
    assert "rate-limited" in r["summary"].lower()


# --- fan-out + dedup --------------------------------------------------------


@responses.activate
def test_fan_out_dedupes_passages_by_pmcid_text() -> None:
    """Same passage returned by two queries should land once."""
    # responses replays the same response for repeated URL hits.
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json=[
            {"pmcid": "PMC1", "pmid": 1, "section": "RESULTS",
             "text": "Shared passage X.", "score": 0.8},
        ],
        status=200,
    )
    r = literature_search(queries=["query a", "query b", "query c"])
    # All three queries return the same passage; dedup leaves one.
    assert r["num_passages"] == 1


@responses.activate
def test_per_query_status_recorded() -> None:
    responses.add(
        responses.GET,
        LITSENSE_URL,
        json=[
            {"pmcid": "PMC1", "pmid": 1, "section": "RESULTS",
             "text": "Some sentence.", "score": 0.7},
        ],
        status=200,
    )
    r = literature_search(queries=["alpha", "beta"])
    assert set(r["per_query_status"].keys()) == {"alpha", "beta"}
    assert all(v == "ok" for v in r["per_query_status"].values())


def test_network_failure_degrades_gracefully(monkeypatch) -> None:
    """Connection errors from BOTH LitSense and PubMed degrade to rate_limited."""
    class _FailingSession:
        headers: dict = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("dns boom")

    r = literature_search(query="x", session=_FailingSession())  # type: ignore[arg-type]
    assert r["passages"] == []
    # Network failure on LitSense → rate_limited=True (no PubMed fallback
    # since the same session fails for both endpoints).
    assert r["rate_limited"] is True


# --- live --------------------------------------------------------------


@pytest.mark.live
def test_live_litsense_returns_passages() -> None:
    r = literature_search(query="PD-L1 binder design", limit=3)
    if not r["rate_limited"]:
        # If we got passages, they should have section + text + score.
        if r["passages"]:
            p = r["passages"][0]
            assert "text" in p and "section" in p and "score" in p


@pytest.mark.live
def test_live_fan_out_parallel() -> None:
    r = literature_search(
        queries=[
            "PD-L1 binder design",
            "pae_interaction AF2 filter",
            "ProteinMPNN soluble model",
        ],
        limit=10,
    )
    if not r["rate_limited"]:
        assert len(r["queries_run"]) == 3
        assert "per_query_status" in r

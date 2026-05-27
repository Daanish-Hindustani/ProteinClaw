"""``research.pubmed_search`` — single-query PubMed E-utilities tool."""

from __future__ import annotations

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.pubmed import (
    PUBMED_ESEARCH,
    PUBMED_ESUMMARY,
    _normalize_query,
    _simplify_query,
    pubmed_search,
)


def test_registered() -> None:
    assert "research.pubmed_search" in registry


# --- query helpers ----------------------------------------------------------


def test_normalize_uppercases_boolean_ops() -> None:
    assert _normalize_query("pd-l1 and pd-1 not antibody") == (
        "pd-l1 AND pd-1 NOT antibody"
    )


def test_normalize_preserves_quoted_phrases() -> None:
    out = _normalize_query('"and the band" or rock')
    assert '"and the band"' in out and " OR " in out


def test_simplify_query_returns_shorter_variants() -> None:
    q = "PD-L1 binder design hotspot residues clinical trial review meta-analysis"
    variants = _simplify_query(q)
    assert variants  # has at least one shorter form
    assert all(len(v.split()) <= 5 for v in variants)


def test_simplify_short_query_yields_nothing() -> None:
    assert _simplify_query("PD-L1 binder") == []


# --- arg validation ---------------------------------------------------------


def test_invalid_args_when_blank() -> None:
    r = pubmed_search(query="   ")
    assert r["error"] == "invalid_args"


# --- happy path -------------------------------------------------------------


@responses.activate
def test_returns_paper_metadata_on_hit() -> None:
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": ["111", "222"], "count": "2"}},
        status=200,
    )
    responses.add(
        responses.GET,
        PUBMED_ESUMMARY,
        json={
            "result": {
                "111": {
                    "title": "A binder design paper",
                    "source": "Nature",
                    "pubdate": "2024 May",
                    "authors": [{"name": "Smith J"}, {"name": "Jones K"}],
                    "articleids": [{"idtype": "doi", "value": "10.1/abc"}],
                },
                "222": {
                    "title": "Another paper",
                    "source": "Cell",
                    "pubdate": "2023",
                    "authors": [],
                    "articleids": [],
                },
            }
        },
        status=200,
    )
    r = pubmed_search(query="PD-L1 binder design")
    assert r["total_count"] == 2
    assert len(r["papers"]) == 2
    first = r["papers"][0]
    assert first["pmid"] == "111"
    assert first["title"] == "A binder design paper"
    assert first["doi"] == "10.1/abc"
    assert first["year"] == "2024"
    assert first["first_author"] == "Smith J"


# --- failure / rate-limit modes --------------------------------------------


@responses.activate
def test_persistent_429_marks_rate_limited() -> None:
    for _ in range(3):
        responses.add(responses.GET, PUBMED_ESEARCH, status=429, body="slow")
    r = pubmed_search(query="x")
    assert r["rate_limited"] is True
    assert r["papers"] == []


@responses.activate
def test_429_then_200_recovers_via_retry() -> None:
    responses.add(responses.GET, PUBMED_ESEARCH, status=429, body="slow")
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": ["1"], "count": "1"}},
        status=200,
    )
    responses.add(
        responses.GET,
        PUBMED_ESUMMARY,
        json={"result": {"1": {"title": "ok", "pubdate": "2024", "authors": []}}},
        status=200,
    )
    r = pubmed_search(query="x")
    assert r["rate_limited"] is False
    assert len(r["papers"]) == 1


@responses.activate
def test_simplification_fallback_when_zero_hits() -> None:
    """Long query returns 0 → tool retries with the shorter variant and that wins."""
    long_q = "PD-L1 binder design hotspot residues clinical trial meta-analysis 2024"
    short_q = _simplify_query(long_q)[0]  # first 5 words

    # First ESearch (long query): zero hits.
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": [], "count": "0"}},
        status=200,
    )
    # Second ESearch (short query): one hit.
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": ["42"], "count": "1"}},
        status=200,
    )
    responses.add(
        responses.GET,
        PUBMED_ESUMMARY,
        json={
            "result": {
                "42": {"title": "Hit via simplified query", "pubdate": "2024",
                       "authors": [{"name": "X"}]}
            }
        },
        status=200,
    )
    r = pubmed_search(query=long_q)
    assert r["query"] == short_q
    assert r["original_query"] == long_q
    assert r["papers"][0]["pmid"] == "42"
    assert "simplified" in r["summary"].lower()


@responses.activate
def test_no_results_returns_empty_summary() -> None:
    """Short query (no simplification path) with zero hits returns clean empty result."""
    responses.add(
        responses.GET,
        PUBMED_ESEARCH,
        json={"esearchresult": {"idlist": [], "count": "0"}},
        status=200,
    )
    r = pubmed_search(query="zzznoresults")
    assert r["papers"] == []
    assert r["total_count"] == 0
    assert "No PubMed results" in r["summary"]


# --- live -------------------------------------------------------------------


@pytest.mark.live
def test_live_pubmed_search() -> None:
    r = pubmed_search(query="PD-L1 binder design", max_results=3)
    if not r.get("rate_limited") and r["papers"]:
        p = r["papers"][0]
        assert p["pmid"] and p["title"]

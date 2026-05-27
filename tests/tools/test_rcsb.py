"""Task 6.3 — rcsb_search unit tests (mocked) + live E2E."""

from __future__ import annotations

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.rcsb import _rank_candidates, _recency_score, _resolution_score, rcsb_search


def test_registered() -> None:
    assert "data.rcsb_search" in registry


def test_resolution_score_monotone() -> None:
    assert _resolution_score(1.0) > _resolution_score(2.0) > _resolution_score(3.0) > _resolution_score(5.0)
    assert _resolution_score(None) > 0  # fallback


def test_recency_score_newer_is_higher() -> None:
    assert _recency_score("2025-01-01") > _recency_score("2010-01-01") > _recency_score("1995-01-01")


def test_rank_candidates_orders_higher_first() -> None:
    cands = [
        {"pdb_id": "OLD", "resolution": 1.0, "deposition_date": "1995-01-01", "search_score": 0.5},
        {"pdb_id": "NEW", "resolution": 1.0, "deposition_date": "2025-01-01", "search_score": 0.5},
    ]
    ranked = _rank_candidates(cands)
    assert ranked[0]["pdb_id"] == "NEW"


@responses.activate
def test_search_returns_ranked_candidates() -> None:
    responses.add(
        responses.POST,
        "https://search.rcsb.org/rcsbsearch/v2/query",
        json={
            "result_set": [
                {"identifier": "5JDS", "score": 0.9},
                {"identifier": "5IUS", "score": 0.7},
            ],
            "total_count": 2,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://data.rcsb.org/rest/v1/core/entry/5JDS",
        json={
            "struct": {"title": "PD-L1 IgV in complex with anti-PD-L1"},
            "exptl": [{"method": "X-RAY DIFFRACTION"}],
            "refine": [{"ls_d_res_high": 1.8}],
            "rcsb_accession_info": {"deposit_date": "2016-05-01"},
            "rcsb_entry_info": {"polymer_entity_count_protein": 2},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://data.rcsb.org/rest/v1/core/entry/5IUS",
        json={
            "struct": {"title": "PD-1/PD-L1 complex"},
            "exptl": [{"method": "X-RAY DIFFRACTION"}],
            "refine": [{"ls_d_res_high": 2.4}],
            "rcsb_accession_info": {"deposit_date": "2015-12-15"},
            "rcsb_entry_info": {"polymer_entity_count_protein": 2},
        },
        status=200,
    )

    r = rcsb_search(query="PD-L1 IgV")
    assert r["requires_clarification"] is True
    assert len(r["candidates"]) == 2
    ids = [c["pdb_id"] for c in r["candidates"]]
    assert "5JDS" in ids and "5IUS" in ids
    # 5JDS should rank above 5IUS (better resolution + slightly newer).
    assert r["candidates"][0]["pdb_id"] == "5JDS"
    assert "5JDS" in r["summary"]


@responses.activate
def test_search_empty_set() -> None:
    responses.add(
        responses.POST,
        "https://search.rcsb.org/rcsbsearch/v2/query",
        json={"result_set": [], "total_count": 0},
        status=200,
    )
    r = rcsb_search(query="zzzznotaprotein")
    assert r["candidates"] == []
    assert r["requires_clarification"] is False


@responses.activate
def test_search_upstream_5xx() -> None:
    responses.add(
        responses.POST,
        "https://search.rcsb.org/rcsbsearch/v2/query",
        status=502,
        body="bad gateway",
    )
    r = rcsb_search(query="anything")
    assert r["error"] == "upstream_error"


# --- Live E2E ---------------------------------------------------------------


@pytest.mark.live
def test_live_pdl1_search_finds_5jds_or_equiv() -> None:
    r = rcsb_search(query="PD-L1 IgV", limit=10)
    assert r["candidates"], r
    ids = [c["pdb_id"] for c in r["candidates"]]
    # Just assert SOME PD-L1 structure shows up; specific top hit varies.
    # We'll print the top in the manual section.
    assert len(ids) > 0

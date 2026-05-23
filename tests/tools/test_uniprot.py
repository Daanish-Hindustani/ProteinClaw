"""Task 6.1 — uniprot_fetch unit tests (mocked) + live E2E (opt-in)."""

from __future__ import annotations

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.uniprot import _looks_like_accession, uniprot_fetch


def test_registered() -> None:
    assert "data.uniprot_fetch" in registry
    t = registry.get_tool("data.uniprot_fetch")
    assert not t.requires_gpu


def test_accession_regex_positives() -> None:
    for acc in ["P12345", "Q9Y6K9", "A0A024RBG1", "O15530"]:
        assert _looks_like_accession(acc), acc


def test_accession_regex_negatives() -> None:
    for s in ["PD-L1", "p53", "abc", "12345", ""]:
        assert not _looks_like_accession(s), s


@responses.activate
def test_direct_accession_fetch_success() -> None:
    responses.add(
        responses.GET,
        "https://rest.uniprot.org/uniprotkb/P12345",
        json={
            "primaryAccession": "P12345",
            "proteinDescription": {"recommendedName": {"fullName": {"value": "Test protein"}}},
            "organism": {"scientificName": "Homo sapiens"},
            "sequence": {"value": "MEEPQSDPSV"},
            "features": [
                {
                    "type": "Domain",
                    "description": "Test domain",
                    "location": {"start": {"value": 1}, "end": {"value": 5}},
                },
                {"type": "Active site"},  # ignored
            ],
        },
        status=200,
    )
    r = uniprot_fetch(query="P12345")
    assert r["accession"] == "P12345"
    assert r["protein_name"] == "Test protein"
    assert r["organism"] == "Homo sapiens"
    assert r["sequence"] == "MEEPQSDPSV"
    assert r["length"] == 10
    assert r["domains"] == [{"name": "Test domain", "start": 1, "end": 5}]
    assert "P12345" in r["summary"]


@responses.activate
def test_accession_404_returns_invalid_query() -> None:
    # O00000 matches the [OPQ][0-9][A-Z0-9]{3}[0-9] form of the UniProt regex.
    responses.add(
        responses.GET, "https://rest.uniprot.org/uniprotkb/O00000", status=404, body="not found"
    )
    r = uniprot_fetch(query="O00000")
    assert r["error"] == "invalid_query"
    assert "O00000" in r["summary"]


@responses.activate
def test_name_search_single_match() -> None:
    responses.add(
        responses.GET,
        "https://rest.uniprot.org/uniprotkb/search",
        json={
            "results": [
                {
                    "primaryAccession": "Q9NZQ7",
                    "proteinDescription": {
                        "recommendedName": {"fullName": {"value": "PD-L1"}}
                    },
                    "organism": {"scientificName": "Homo sapiens"},
                    "sequence": {"value": "MRIFAV" * 10},
                    "features": [],
                }
            ]
        },
        status=200,
    )
    r = uniprot_fetch(query="PD-L1")
    assert r["accession"] == "Q9NZQ7"
    assert "requires_clarification" not in r


@responses.activate
def test_name_search_ambiguous_flags_clarification() -> None:
    responses.add(
        responses.GET,
        "https://rest.uniprot.org/uniprotkb/search",
        json={
            "results": [
                {
                    "primaryAccession": "P04637",
                    "proteinDescription": {"recommendedName": {"fullName": {"value": "TP53 human"}}},
                    "organism": {"scientificName": "Homo sapiens"},
                    "sequence": {"value": "MEEPQSDPSV"},
                    "features": [],
                },
                {
                    "primaryAccession": "P02340",
                    "proteinDescription": {"recommendedName": {"fullName": {"value": "TP53 mouse"}}},
                    "organism": {"scientificName": "Mus musculus"},
                    "sequence": {"value": "MEEPQSDLSI"},
                    "features": [],
                },
            ]
        },
        status=200,
    )
    r = uniprot_fetch(query="p53")
    assert r.get("requires_clarification") is True
    assert len(r["candidates"]) == 2
    assert {c["organism"] for c in r["candidates"]} == {"Homo sapiens", "Mus musculus"}


@responses.activate
def test_name_search_no_results() -> None:
    responses.add(
        responses.GET,
        "https://rest.uniprot.org/uniprotkb/search",
        json={"results": []},
        status=200,
    )
    r = uniprot_fetch(query="zzzzznotaprotein")
    assert r["error"] == "invalid_query"


@responses.activate
def test_upstream_5xx_returns_upstream_error() -> None:
    responses.add(
        responses.GET, "https://rest.uniprot.org/uniprotkb/P12345", status=503
    )
    r = uniprot_fetch(query="P12345")
    assert r["error"] == "upstream_error"
    assert r["metrics"]["http_status"] == 503


# --- Live E2E (opt-in) ------------------------------------------------------


@pytest.mark.live
def test_live_pdl1_accession_fetch() -> None:
    """Q9NZQ7 is human PD-L1. Verifies the real UniProt is reachable + parser is correct."""
    r = uniprot_fetch(query="Q9NZQ7")
    assert r["accession"] == "Q9NZQ7"
    # UniProt's recommendedName is the formal description; aliases live elsewhere.
    name_lower = r["protein_name"].lower()
    assert "programmed cell death" in name_lower or "pd-l1" in name_lower
    assert r["length"] > 250  # human PD-L1 is 290 aa
    assert r["sequence"].startswith("M")


@pytest.mark.live
def test_live_name_search() -> None:
    r = uniprot_fetch(query="PD-L1", organism="Homo sapiens", limit=3)
    # Either a single resolved hit or a candidate list.
    assert "accession" in r or "candidates" in r

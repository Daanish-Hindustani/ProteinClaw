"""Task 6.5 — web_search unit tests + live E2E."""

from __future__ import annotations

import pytest
import responses

from proteinclaw.tools import registry
from proteinclaw.tools.web import _parse_html_results, _unwrap_ddg_redirect, web_search


def test_registered() -> None:
    assert "research.web_search" in registry


def test_unwrap_redirect() -> None:
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage&rut=abc"
    assert _unwrap_ddg_redirect(wrapped) == "https://example.org/page"


def test_unwrap_passthrough() -> None:
    assert _unwrap_ddg_redirect("https://example.org/x") == "https://example.org/x"


def test_parse_html_extracts_results() -> None:
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa">'
        "Example A</a>"
        '<a class="result__snippet">Snippet about A.</a>'
        '<a class="result__a" href="https://example.org/b">Example <b>B</b></a>'
        '<a class="result__snippet">Snippet <i>B</i>.</a>'
    )
    results = _parse_html_results(html, limit=5)
    assert len(results) == 2
    assert results[0]["url"] == "https://example.org/a"
    assert results[0]["title"] == "Example A"
    assert results[1]["title"] == "Example B"
    assert results[1]["snippet"] == "Snippet B."


@responses.activate
def test_ia_returns_abstract_short_circuits_html() -> None:
    responses.add(
        responses.GET,
        "https://api.duckduckgo.com/",
        json={
            "Heading": "ProteinClaw",
            "AbstractURL": "https://github.com/Daanish-Hindustani/ProteinClaw",
            "AbstractText": "An agentic CLI for protein binder design.",
            "RelatedTopics": [],
        },
        status=200,
    )
    # We pass limit=1 so the HTML fallback is not triggered.
    r = web_search(query="ProteinClaw", limit=1)
    assert r["results"][0]["source"] == "duckduckgo-ia-abstract"
    assert "github.com" in r["results"][0]["url"]
    assert r["metrics"]["html_count"] == 0


@responses.activate
def test_ia_plus_html_fallback_combine() -> None:
    responses.add(
        responses.GET,
        "https://api.duckduckgo.com/",
        json={
            "Heading": "ProteinClaw",
            "AbstractURL": "https://github.com/Daanish-Hindustani/ProteinClaw",
            "AbstractText": "An agentic CLI for protein binder design.",
            "RelatedTopics": [],
        },
        status=200,
    )
    responses.add(
        responses.POST,
        "https://html.duckduckgo.com/html/",
        body=(
            '<a class="result__a" href="https://example.org/x">X</a>'
            '<a class="result__snippet">X snippet</a>'
            '<a class="result__a" href="https://example.org/y">Y</a>'
            '<a class="result__snippet">Y snippet</a>'
        ),
        status=200,
    )
    r = web_search(query="ProteinClaw", limit=5)
    assert r["metrics"]["ia_count"] >= 1
    assert r["metrics"]["html_count"] >= 1
    assert len(r["results"]) >= 2


@responses.activate
def test_total_failure_returns_empty_no_throw() -> None:
    responses.add(responses.GET, "https://api.duckduckgo.com/", status=503)
    responses.add(responses.POST, "https://html.duckduckgo.com/html/", status=503)
    r = web_search(query="anything")
    assert r["results"] == []
    assert "unavailable" in r["summary"]


# --- Live E2E ---------------------------------------------------------------


@pytest.mark.live
def test_live_search_returns_something() -> None:
    r = web_search(query="RFdiffusion3 binder design tips", limit=5)
    assert "results" in r
    # No strict assertion: DDG can rate-limit / change layout. We're testing
    # that the call returns the contract shape, not that the result count is non-zero.
    assert isinstance(r["results"], list)

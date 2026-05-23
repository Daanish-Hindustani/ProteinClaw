"""``research.literature_search`` — Semantic Scholar paper search.

Quota-aware by design (PRD §6.2, §10.2): rate-limit responses do **not** fail
the run; they return an empty result set with a clear summary so the agent
can proceed without literature context. Other HTTP errors degrade the same
way (logged loudly but non-fatal).

A simple per-process token bucket smooths out client-side burstiness so we
don't hammer Semantic Scholar on a tight agent loop. bioRxiv fallback is
deferred — Semantic Scholar already ingests bioRxiv, so the extra hop
rarely adds value for v1 (see NOTES.md).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

# Unauthenticated SS limit ≈ 100 req/5 min. Stay well below.
_MIN_INTERVAL_S = 1.0
_last_call_lock = threading.Lock()
_last_call_t: float = 0.0


def _throttle() -> None:
    global _last_call_t
    with _last_call_lock:
        now = time.monotonic()
        delta = now - _last_call_t
        if delta < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - delta)
        _last_call_t = time.monotonic()


_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 2,
            "description": "Free-text query (e.g. 'PD-L1 binder design').",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 25,
            "default": 5,
        },
        "year_min": {
            "type": "integer",
            "minimum": 1900,
            "description": "Filter to papers from this year onward.",
        },
    },
    "required": ["query"],
}


def _format_paper(p: dict[str, Any]) -> dict[str, Any]:
    authors = [(a.get("name") or "") for a in (p.get("authors") or [])][:6]
    abstract = p.get("abstract") or ""
    preview = abstract if len(abstract) <= 400 else abstract[:400] + "…"
    return {
        "paper_id": p.get("paperId", ""),
        "title": p.get("title") or "",
        "year": p.get("year"),
        "venue": p.get("venue") or "",
        "authors": authors,
        "url": p.get("url") or "",
        "abstract_preview": preview,
    }


@registry.register(
    name="research.literature_search",
    display_name="Literature search (Semantic Scholar)",
    description=(
        "Search the Semantic Scholar Graph API for papers matching a query. "
        "Returns paper titles, years, venues, authors, URLs, and abstract previews. "
        "On rate-limit or upstream error, returns an empty result set with a clear "
        "summary — never fails the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "Use early in target resolution and at the start of each design round. "
        "Combine target name with technique terms (e.g. 'PD-L1 binder de novo RFdiffusion')."
    ),
)
def literature_search(
    *,
    query: str,
    limit: int = 5,
    year_min: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    sess = session or make_session()
    _throttle()

    params: dict[str, Any] = {
        "query": query,
        "limit": str(limit),
        "fields": "title,year,authors,abstract,url,venue",
    }
    if year_min is not None:
        params["year"] = f"{year_min}-"

    try:
        status, body = get_json(SEMANTIC_SCHOLAR_URL, params=params, session=sess)
    except requests.RequestException as exc:
        # Network blip → treat as rate-limited / unavailable.
        return {
            "summary": f"Literature search unavailable ({exc.__class__.__name__})",
            "query": query,
            "results": [],
            "rate_limited": True,
            "metrics": {"error": str(exc)},
        }

    if status == 429:
        return {
            "summary": "Literature search rate-limited by Semantic Scholar",
            "query": query,
            "results": [],
            "rate_limited": True,
            "metrics": {"http_status": 429},
        }
    if status >= 400 or not isinstance(body, dict):
        return {
            "summary": f"Literature search unavailable (HTTP {status})",
            "query": query,
            "results": [],
            "rate_limited": False,
            "metrics": {"http_status": status},
        }

    papers_raw = body.get("data") or []
    papers = [_format_paper(p) for p in papers_raw]
    return {
        "summary": (
            f"Found {len(papers)} paper(s) for {query!r}"
            if papers
            else f"No papers matched {query!r}"
        ),
        "query": query,
        "results": papers,
        "rate_limited": False,
        "metrics": {"http_status": status, "num_results": len(papers)},
    }


__all__ = ["literature_search"]

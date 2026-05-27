"""``research.pubmed_search`` — direct PubMed E-utilities query (no API key).

PubMed E-utilities is free and requires no authentication. Anonymous
quota is ~3 req/sec, but a single ESearch + ESummary pair is well below
that ceiling, so this tool almost never rate-limits in practice.

Why this exists alongside ``research.literature_search``:

* ``literature_search`` is LitSense-first (passage-level) and the
  LitSense endpoint is the one that throttles under fan-out. When
  LitSense is unhealthy or returns nothing, the agent has nowhere
  to go.
* ``pubmed_search`` is a clean second surface — single sequential
  call to PubMed, paper-level metadata, retry-with-backoff on 429.
  Use it when the agent wants reliable paper hits and doesn't
  need full-text passages.

Pattern borrowed from celltype-agent's literature.pubmed_search:
sequential ESearch → ESummary, query-simplification fallback when
PubMed's strict AND-everything semantics return zero results.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json_with_retry, make_session

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

_BOOL_OP = re.compile(r"\b(and|or|not)\b", re.IGNORECASE)


_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 2,
            "description": (
                "Single query string. PubMed ANDs all terms by default, so "
                "long queries (8+ terms) often return zero; this tool will "
                "automatically retry with shorter variants."
            ),
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 20,
            "description": "Cap on returned papers.",
        },
    },
    "required": ["query"],
}


def _normalize_query(q: str) -> str:
    """Uppercase the standalone boolean operators PubMed expects."""
    parts = re.split(r'(".*?")', q)
    out: list[str] = []
    for part in parts:
        if part.startswith('"'):
            out.append(part)
        else:
            out.append(_BOOL_OP.sub(lambda m: m.group(0).upper(), part))
    return " ".join("".join(out).split())


def _simplify_query(q: str) -> list[str]:
    """Progressively shorter variants when the full query returned 0 hits."""
    words = [w for w in q.split() if w.upper() not in ("AND", "OR", "NOT")]
    if len(words) <= 4:
        return []
    shorter: list[str] = []
    if len(words) > 6:
        shorter.append(" ".join(words[:5]))
    shorter.append(" ".join(words[:3]))
    return shorter


def _esearch(
    q: str, *, session: requests.Session, max_results: int
) -> tuple[list[str], int, Optional[str]]:
    """ESearch → (pmids, total_count, error_or_None)."""
    try:
        status, body = get_json_with_retry(
            PUBMED_ESEARCH,
            params={
                "db": "pubmed",
                "term": _normalize_query(q),
                "retmax": str(max_results),
                "retmode": "json",
                "sort": "relevance",
            },
            session=session,
            timeout=15.0,
        )
    except requests.RequestException as exc:
        return [], 0, f"network: {exc.__class__.__name__}"
    if status == 429:
        return [], 0, "rate_limited"
    if status >= 400 or not isinstance(body, dict):
        return [], 0, f"http_{status}"
    result = body.get("esearchresult") or {}
    ids = result.get("idlist") or []
    try:
        total = int(result.get("count") or 0)
    except (TypeError, ValueError):
        total = 0
    return list(ids), total, None


def _esummary(
    ids: list[str], *, session: requests.Session
) -> tuple[list[dict[str, Any]], Optional[str]]:
    if not ids:
        return [], None
    try:
        status, body = get_json_with_retry(
            PUBMED_ESUMMARY,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            session=session,
            timeout=15.0,
        )
    except requests.RequestException as exc:
        return [], f"network: {exc.__class__.__name__}"
    if status == 429:
        return [], "rate_limited"
    if status >= 400 or not isinstance(body, dict):
        return [], f"http_{status}"
    result = body.get("result") or {}
    papers: list[dict[str, Any]] = []
    for pmid in ids:
        rec = result.get(pmid)
        if not isinstance(rec, dict):
            continue
        authors = [a.get("name") or "" for a in (rec.get("authors") or [])]
        first_author = authors[0] if authors else ""
        doi = next(
            (a.get("value", "") for a in (rec.get("articleids") or [])
             if isinstance(a, dict) and a.get("idtype") == "doi"),
            "",
        )
        papers.append({
            "pmid": pmid,
            "title": rec.get("title") or "",
            "first_author": first_author,
            "authors": authors[:5],
            "journal": rec.get("source") or "",
            "pub_date": rec.get("pubdate") or "",
            "year": (rec.get("pubdate") or "")[:4],
            "doi": doi,
        })
    return papers, None


@registry.register(
    name="research.pubmed_search",
    display_name="PubMed search (NCBI E-utilities)",
    description=(
        "Single-query PubMed search via NCBI E-utilities (free, no API key). "
        "Returns paper-level metadata (title, authors, journal, year, DOI, "
        "PMID). Sequential ESearch + ESummary with exponential backoff on "
        "429/5xx; if the full query returns 0 hits, automatically retries "
        "with progressively shorter variants. Use this when you want "
        "reliable paper hits without LitSense's passage-level cost or "
        "fan-out throttling. Quota / network failures degrade to empty "
        "results, never fail the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "Default literature surface when you just need paper context. "
        "Prefer `research.literature_search` only when you want sentence-"
        "level passages from PubMed Central full-text."
    ),
)
def pubmed_search(
    *,
    query: str,
    max_results: int = 20,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {
            "summary": "Error: pubmed_search requires `query`",
            "error": "invalid_args",
            "metrics": {},
        }

    sess = session or make_session()
    t0 = time.monotonic()
    used_query = q
    pmids, total, err = _esearch(q, session=sess, max_results=max_results)

    if not pmids and err is None:
        for shorter in _simplify_query(q):
            pmids2, total2, err2 = _esearch(
                shorter, session=sess, max_results=max_results
            )
            if err2:
                err = err2
                break
            if pmids2:
                pmids, total, used_query = pmids2, total2, shorter
                break

    if err == "rate_limited":
        return {
            "summary": "PubMed rate-limited — degraded per PRD §10.2",
            "query": q,
            "papers": [],
            "results": [],
            "rate_limited": True,
            "metrics": {"elapsed_s": round(time.monotonic() - t0, 3)},
        }
    if err:
        return {
            "summary": f"PubMed search failed ({err})",
            "query": q,
            "papers": [],
            "results": [],
            "error": err,
            "metrics": {"elapsed_s": round(time.monotonic() - t0, 3)},
        }

    papers, sum_err = _esummary(pmids, session=sess)
    if sum_err == "rate_limited":
        return {
            "summary": "PubMed ESummary rate-limited — degraded per PRD §10.2",
            "query": q,
            "papers": [],
            "results": [],
            "rate_limited": True,
            "metrics": {"elapsed_s": round(time.monotonic() - t0, 3)},
        }

    elapsed = time.monotonic() - t0
    if not papers:
        return {
            "summary": f"No PubMed results for '{q}'",
            "query": q,
            "papers": [],
            "results": [],
            "total_count": total,
            "rate_limited": False,
            "metrics": {"elapsed_s": round(elapsed, 3)},
        }

    summary = (
        f"PubMed '{used_query}': {total} total, returning {len(papers)}"
        + (f" (simplified from '{q}')" if used_query != q else "")
    )
    return {
        "summary": summary,
        "query": used_query,
        "original_query": q,
        "total_count": total,
        "papers": papers,
        # Back-compat alias so callers that look at `results` work too.
        "results": papers,
        "rate_limited": False,
        "metrics": {"elapsed_s": round(elapsed, 3), "num_results": len(papers)},
    }


__all__ = ["pubmed_search"]

"""``research.literature_search`` — single-query LitSense + PubMed fallback.

Why LitSense first: it returns **passage-level** results (one sentence
plus its section heading) from PubMed Central full-text, which is what
an LLM actually wants to read. PubMed E-utilities only give title +
abstract — useful but lower density.

Design notes:

* **No fan-out.** Earlier versions ran up to 15 queries in parallel
  against LitSense, which is what kept tripping NCBI's 429 limits.
  This tool now does one sequential LitSense call per invocation;
  if the agent needs to triangulate, it calls us multiple times.
* **Retry-with-backoff on 429 / 5xx** via ``_http.get_json_with_retry``
  (pattern borrowed from celltype-agent). One transient throttle no
  longer marks the query as failed.
* **PubMed fallback** when LitSense returns no passages. For richer
  paper-level metadata use the dedicated ``research.pubmed_search``
  tool — this fallback just gives titles.
* **Quota-aware**: persistent HTTP 429 / 5xx / network error degrades
  to ``rate_limited: True`` with empty results — never fails the run
  (PRD §10.2).
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json_with_retry, make_session

LITSENSE_URL = "https://www.ncbi.nlm.nih.gov/research/litsense-api/api/"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

_NON_WORD = re.compile(r"[^\w\s\-/]")


_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 2,
            "description": "Single search query (one call per invocation).",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 10,
            "description": "Max passages to return.",
        },
        "min_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.3,
            "description": "Discard LitSense passages below this score.",
        },
        "with_pubmed_fallback": {
            "type": "boolean",
            "default": True,
            "description": (
                "When LitSense returns no passages, also try PubMed "
                "esearch+esummary for paper-level metadata."
            ),
        },
    },
    "required": ["query"],
}


def _query_litsense(
    q: str,
    *,
    session: requests.Session,
    min_score: float,
    max_passages: int,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Hit LitSense once (with retry). Returns ``(passages, error_or_None)``."""
    try:
        status, body = get_json_with_retry(
            LITSENSE_URL,
            params={"query": q, "rerank": "true"},
            session=session,
            timeout=25.0,
        )
    except requests.RequestException as exc:
        return [], f"network: {exc.__class__.__name__}"
    if status == 429:
        return [], "rate_limited"
    if status >= 400:
        return [], f"http_{status}"
    if isinstance(body, dict):
        return [], "no_passages"
    if not isinstance(body, list):
        return [], "bad_payload"
    passages: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        score = item.get("score") or 0.0
        if score < min_score:
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        passages.append({
            "pmcid": item.get("pmcid"),
            "pmid": item.get("pmid"),
            "section": item.get("section") or "",
            "text": text,
            "score": float(score),
            "query_origin": q,
            "source": "litsense",
        })
    passages.sort(key=lambda p: p["score"], reverse=True)
    return passages[:max_passages], None


def _query_pubmed_fallback(
    q: str, *, session: requests.Session, n: int = 5
) -> list[dict[str, Any]]:
    """Cheap PubMed esearch + esummary. Paper-level only (no passages)."""
    try:
        status, body = get_json_with_retry(
            PUBMED_ESEARCH,
            params={
                "db": "pubmed",
                "term": q,
                "retmode": "json",
                "retmax": str(n),
                "sort": "relevance",
            },
            session=session,
            timeout=15.0,
        )
    except requests.RequestException:
        return []
    if status >= 400 or not isinstance(body, dict):
        return []
    ids = (body.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []
    try:
        status, body = get_json_with_retry(
            PUBMED_ESUMMARY,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            session=session,
            timeout=15.0,
        )
    except requests.RequestException:
        return []
    if status >= 400 or not isinstance(body, dict):
        return []
    result = body.get("result") or {}
    papers: list[dict[str, Any]] = []
    for pmid in ids:
        rec = result.get(pmid)
        if not isinstance(rec, dict):
            continue
        title = rec.get("title") or ""
        year = (rec.get("pubdate") or "")[:4]
        authors = ", ".join(
            (a.get("name") or "") for a in (rec.get("authors") or [])[:5]
        )
        papers.append({
            "pmid": pmid,
            "pmcid": None,
            "section": "TITLE",
            "text": f"{title}  ({authors}, {year})" if year else title,
            "score": 0.5,
            "query_origin": q,
            "source": "pubmed",
            "title": title,
            "year": year,
            "authors": authors,
        })
    return papers


@registry.register(
    name="research.literature_search",
    display_name="Literature search (LitSense + PubMed)",
    description=(
        "Single-query passage-level search over PubMed Central via NCBI "
        "LitSense, with PubMed esearch+esummary fallback. Returns SENTENCE-"
        "level snippets + their section headings + PMC IDs — far more useful "
        "to read than paper abstracts. One sequential call per invocation "
        "(no fan-out), retry-with-backoff on 429/5xx. Quota / network "
        "failures degrade to empty results, never fail the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "Pass one focused query at a time (e.g. \"PD-L1 binder design hotspot "
        "residues\"). To triangulate a topic, call this tool 2-3 times with "
        "different framings. If you just need paper-level metadata (title + "
        "authors + DOI), prefer `research.pubmed_search` — it rarely throttles."
    ),
)
def literature_search(
    *,
    query: str,
    limit: int = 10,
    min_score: float = 0.3,
    with_pubmed_fallback: bool = True,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    q = (query or "").strip() if isinstance(query, str) else ""
    if not q:
        return {
            "summary": "Error: literature_search requires `query`",
            "error": "invalid_args",
            "metrics": {},
        }

    sess = session or make_session()
    t0 = time.monotonic()

    passages, ls_err = _query_litsense(
        q, session=sess, min_score=min_score, max_passages=limit
    )
    source = "litsense" if passages else None
    # Treat 429 / 5xx / network blips as an upstream issue worth flagging,
    # matching the PRD §10.2 graceful-degradation contract.
    upstream_prefixes = ("rate_limited", "network", "http_", "bad_payload")
    rate_limited = bool(ls_err) and any(ls_err.startswith(p) for p in upstream_prefixes)

    if not passages and with_pubmed_fallback and ls_err != "rate_limited":
        passages = _query_pubmed_fallback(q, session=sess, n=min(limit, 10))
        if passages:
            source = "pubmed_fallback"
            rate_limited = False

    passages = passages[:limit]
    elapsed = time.monotonic() - t0

    by_pmcid: dict[str, list[dict[str, Any]]] = {}
    for p in passages:
        key = p.get("pmcid") or f"pmid_{p.get('pmid')}" or "_unknown"
        by_pmcid.setdefault(key, []).append(p)
    n_papers = len(by_pmcid)

    if not passages and rate_limited:
        summary = (
            f"Literature search rate-limited for '{q}' — degraded per PRD §10.2"
        )
    elif not passages:
        summary = (
            f"No passages matched '{q}' (LitSense"
            + (" + PubMed fallback" if with_pubmed_fallback else "")
            + " empty)"
        )
    else:
        summary = (
            f"Found {len(passages)} passages from {n_papers} paper(s) "
            f"for '{q}' via {source} in {elapsed:.1f}s"
        )

    return {
        "summary": summary,
        "query": q,
        "source": source,
        "passages": passages,
        "by_pmcid": by_pmcid,
        "num_passages": len(passages),
        "num_papers": n_papers,
        # Back-compat field for v1 single-query API.
        "results": passages,
        "rate_limited": rate_limited,
        "metrics": {"elapsed_s": round(elapsed, 3)},
    }


__all__ = ["literature_search"]

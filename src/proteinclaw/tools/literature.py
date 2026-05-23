"""``research.literature_search`` — NCBI LitSense (primary) + PubMed (fallback).

Why LitSense first: it returns **passage-level** results (one sentence
plus its section heading) from PubMed Central full-text, which is what
an LLM actually wants to read. PubMed E-utilities only give title +
abstract — useful but lower density.

Patterns we borrow from a previous deep-research agent that hammered
the same APIs (the user surfaced these explicitly):

* **Parallel query fan-out** via ``ThreadPoolExecutor(max_workers=10)``.
  The agent can pass ``queries=[...]`` (up to 15) and we hit LitSense
  concurrently. Single-string ``query=`` still works for back-compat.
* **Passage-level dedup + score-sort** so the agent sees the most
  relevant 20 sentences across all queries rather than 100 from each.
* **Stop-when-enough** loop: once we accumulate ``stop_when_enough``
  unique passages, later concurrent results are still merged but we
  return early on the ranking pass.
* **404/empty fallback**: LitSense returns a ``{detail: "..."}`` JSON
  object when no sentence matches; treat as empty-not-error and try
  PubMed esearch with the same query. If both empty, the per-query
  result is empty.
* **Quota-aware**: any HTTP 429 / 5xx / network error degrades to
  ``rate_limited: True`` with empty results — never fails the run
  (PRD §10.2).
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session

LITSENSE_URL = "https://www.ncbi.nlm.nih.gov/research/litsense-api/api/"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

# Gentle client-side throttle so a 15-query fan-out doesn't pound either API.
_MIN_INTERVAL_S = 0.2
_last_call_lock = threading.Lock()
_last_call_t: float = 0.0
MAX_WORKERS = 10
MAX_QUERIES = 15

_NON_WORD = re.compile(r"[^\w\s\-/]")


def _throttle() -> None:
    """Per-process pacing — kept small so the ThreadPool can still
    overlap many in-flight requests."""
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
            "description": "Single query string (kept for back-compat).",
        },
        "queries": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 1,
            "maxItems": MAX_QUERIES,
            "description": (
                "List of related queries run in parallel (LitSense fan-out). "
                "Prefer this over `query` when you want to triangulate a "
                "topic from several angles."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 10,
            "description": "Max passages to return TOTAL across all queries.",
        },
        "max_passages_per_query": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "default": 10,
        },
        "min_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.3,
            "description": "Discard LitSense passages below this score.",
        },
        "stop_when_enough": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 20,
            "description": "Cap on unique passages aggregated before truncating.",
        },
        "with_pubmed_fallback": {
            "type": "boolean",
            "default": True,
            "description": (
                "When LitSense returns no passages for a query, also try "
                "PubMed esearch+esummary for paper-level fallback."
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# per-query callers
# ---------------------------------------------------------------------------


def _query_litsense(
    q: str,
    *,
    session: requests.Session,
    min_score: float,
    max_passages: int,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Hit LitSense once. Returns ``(passages, error)``.

    ``error`` is a short reason string when LitSense gave nothing
    usable (so we can decide whether to PubMed-fallback). It is NEVER
    raised — quota / network failures degrade silently per PRD §10.2.
    """
    _throttle()
    try:
        status, body = get_json(
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
    # LitSense returns either a list of passages or a {detail: "..."} dict.
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
    # LitSense pre-sorts but truncate anyway to avoid stuffing each
    # query's worth into the union.
    passages.sort(key=lambda p: p["score"], reverse=True)
    return passages[:max_passages], None


def _query_pubmed_fallback(
    q: str, *, session: requests.Session, n: int = 5
) -> list[dict[str, Any]]:
    """Cheap PubMed esearch + esummary. Paper-level only (no passages)."""
    _throttle()
    try:
        status, body = get_json(
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
    _throttle()
    try:
        status, body = get_json(
            PUBMED_ESUMMARY,
            params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            },
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


# ---------------------------------------------------------------------------
# fan-out driver
# ---------------------------------------------------------------------------


def _normalize_queries(
    query: Optional[str], queries: Optional[list[str]]
) -> list[str]:
    raw = list(queries or [])
    if query:
        raw.append(query)
    cleaned: list[str] = []
    seen: set[str] = set()
    for q in raw:
        if not isinstance(q, str):
            continue
        # Strip noise but keep biological identifiers (P12345, Q9NZQ7, A30).
        q2 = q.strip()
        if not q2:
            continue
        key = q2.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(q2)
    return cleaned[:MAX_QUERIES]


def _fan_out(
    queries: list[str],
    *,
    session: requests.Session,
    min_score: float,
    max_passages_per_query: int,
    with_pubmed_fallback: bool,
    stop_when_enough: int,
) -> tuple[list[dict[str, Any]], dict[str, str], int]:
    """Run all queries in parallel; aggregate + dedup.

    Returns ``(passages, per_query_status, total_seen)`` where
    ``per_query_status[query]`` is "ok" / "empty" / "rate_limited" / "fallback_pubmed".
    """
    passages: list[dict[str, Any]] = []
    per_query: dict[str, str] = {}
    seen_pairs: set[tuple[Any, str]] = set()

    def _one(q: str) -> tuple[str, list[dict[str, Any]], Optional[str]]:
        ls_pass, ls_err = _query_litsense(
            q,
            session=session,
            min_score=min_score,
            max_passages=max_passages_per_query,
        )
        if ls_pass:
            return q, ls_pass, None
        if ls_err in {"rate_limited", "http_429"}:
            return q, [], "rate_limited"
        if with_pubmed_fallback:
            pb = _query_pubmed_fallback(q, session=session, n=5)
            if pb:
                return q, pb, "fallback_pubmed"
        return q, [], ls_err or "empty"

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(_one, q) for q in queries]
        for fut in as_completed(futs):
            q, items, status = fut.result()
            per_query[q] = (
                status if status else ("ok" if items else "empty")
            )
            for item in items:
                # Dedup by (pmcid, text-prefix) so the same sentence from
                # multiple queries collapses to one.
                key = (item.get("pmcid"), item.get("text", "")[:120])
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                passages.append(item)

    passages.sort(key=lambda p: p["score"], reverse=True)
    total_seen = len(passages)
    if stop_when_enough > 0:
        passages = passages[:stop_when_enough]
    return passages, per_query, total_seen


@registry.register(
    name="research.literature_search",
    display_name="Literature search (LitSense + PubMed)",
    description=(
        "Passage-level full-text search over PubMed Central via NCBI LitSense, "
        "with PubMed esearch+esummary fallback. Supports parallel query fan-out: "
        "pass `queries=[...]` (up to 15) and the wrapper hits LitSense "
        "concurrently, dedups, and returns the top-scoring passages across all "
        "queries. Returns SENTENCE-level snippets + their section headings + "
        "PMC IDs — far more useful to read than paper abstracts. Quota / "
        "network failures degrade to empty results, never fail the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "For routine target context, one query is fine. When triangulating a "
        "topic (e.g. PD-L1 binder design AND hotspot residues AND therapeutic "
        "trials), pass `queries=[\"PD-L1 binder design\", \"PD-L1 PD-1 interface "
        "hotspots\", \"anti-PD-L1 antibody clinical trials\"]` — the parallel "
        "fan-out is much faster than calling the tool three times sequentially."
    ),
)
def literature_search(
    *,
    query: Optional[str] = None,
    queries: Optional[list[str]] = None,
    limit: int = 10,
    max_passages_per_query: int = 10,
    min_score: float = 0.3,
    stop_when_enough: int = 20,
    with_pubmed_fallback: bool = True,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    qs = _normalize_queries(query, queries)
    if not qs:
        return {
            "summary": "Error: literature_search requires `query` or `queries`",
            "error": "invalid_args",
            "metrics": {},
        }

    sess = session or make_session()
    t0 = time.monotonic()
    try:
        passages, per_query, total = _fan_out(
            qs,
            session=sess,
            min_score=min_score,
            max_passages_per_query=max_passages_per_query,
            with_pubmed_fallback=with_pubmed_fallback,
            stop_when_enough=stop_when_enough,
        )
    except Exception as exc:  # noqa: BLE001 — never crash the agent
        return {
            "summary": f"Literature search unavailable ({type(exc).__name__})",
            "queries_run": qs,
            "results": [],
            "passages": [],
            "rate_limited": True,
            "metrics": {"error": str(exc)},
        }
    elapsed = time.monotonic() - t0

    # Truncate to user-requested limit (after dedup-sort).
    passages = passages[:limit]

    # Group passages by paper for at-a-glance reading.
    by_pmcid: dict[str, list[dict[str, Any]]] = {}
    for p in passages:
        key = p.get("pmcid") or f"pmid_{p.get('pmid')}" or "_unknown"
        by_pmcid.setdefault(key, []).append(p)

    # Surface rate-limit / upstream-issue flag whenever a query failed for
    # a reason OTHER than "no matches" — the agent should not infer "no
    # literature exists" from a transport failure. Per PRD §10.2 this is
    # part of the deliberate graceful-degradation contract.
    upstream_issue_prefixes = ("rate_limited", "network", "http_", "bad_payload")
    rate_limited = any(
        any(s.startswith(p) for p in upstream_issue_prefixes)
        for s in per_query.values()
    )

    n_papers = len(by_pmcid)
    summary = (
        f"Found {len(passages)} passages from {n_papers} paper(s) "
        f"across {len(qs)} query(s) in {elapsed:.1f}s"
        + (" (rate-limited on at least one query)" if rate_limited else "")
    )
    if not passages and rate_limited:
        summary = (
            f"Literature search rate-limited (no passages returned across "
            f"{len(qs)} query(s)) — degraded per PRD §10.2"
        )
    elif not passages:
        summary = (
            f"No passages matched any of {len(qs)} query(s) "
            f"(LitSense + PubMed fallback both empty)"
        )

    return {
        "summary": summary,
        "queries_run": qs,
        "per_query_status": per_query,
        "passages": passages,
        "by_pmcid": by_pmcid,
        "num_passages": len(passages),
        "num_papers": n_papers,
        "total_passages_seen_before_truncation": total,
        # Back-compat field for the v1 single-query API.
        "results": passages,
        "rate_limited": rate_limited,
        "metrics": {
            "elapsed_s": round(elapsed, 3),
            "num_queries": len(qs),
        },
    }


__all__ = ["literature_search"]

"""``research.web_search`` — DuckDuckGo with parallel query fan-out.

Same pattern as ``research.literature_search``: accept a list of
``queries=[...]`` (up to 10) and run them in parallel via
``ThreadPoolExecutor``. Each query goes through:

  1. DuckDuckGo **Instant Answer** JSON (fast, often empty).
  2. DuckDuckGo **HTML** search page (regex parse — no bs4 dep).
  3. If HTML returned a 4xx, a single **fallback** retry where we
     progressively strip quotes / non-word characters from the query
     (DDG's HTML endpoint sometimes 4xxs on overly-quoted phrases).

Aggregation:
  * Cross-query dedup on the result URL.
  * Sort by source priority (IA-abstract > IA-related > HTML) then by
    insertion order — DDG's HTML rank is approximately relevance.
  * Cap total results at ``limit``.
  * Any total failure → empty results, ``rate_limited: False``,
    summary explains. Never raises.
"""

from __future__ import annotations

import html as _html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session, post_form

IA_URL = "https://api.duckduckgo.com/"
HTML_URL = "https://html.duckduckgo.com/html/"
MAX_WORKERS = 8
MAX_QUERIES = 10

_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_QUOTES_AND_PUNCT = re.compile(r'[\"\'`*+~&]')


_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 2,
            "description": "Single query (back-compat with v1).",
        },
        "queries": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 1,
            "maxItems": MAX_QUERIES,
            "description": (
                "List of related queries run in parallel. Prefer this over "
                "`query` when triangulating a topic."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 10,
            "description": "Total results to return AFTER dedup across queries.",
        },
        "per_query_limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 8,
            "description": "Max results per individual query before dedup.",
        },
    },
}


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _strip_tags(s: str) -> str:
    return _html.unescape(_TAG_RE.sub("", s)).strip()


def _unwrap_ddg_redirect(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/") or href.startswith("/l/"):
        try:
            parsed = urlparse(
                href if href.startswith("http") else "https:" + href
            )
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        except Exception:  # noqa: BLE001
            pass
    return href


def _parse_html_results(html: str, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _RESULT_RE.finditer(html):
        href, title_html, snippet_html = m.group(1), m.group(2), m.group(3)
        url = _unwrap_ddg_redirect(href)
        out.append({
            "title": _strip_tags(title_html),
            "url": url,
            "snippet": _strip_tags(snippet_html),
            "source": "duckduckgo-html",
        })
        if len(out) >= limit:
            break
    return out


def _parse_ia_results(body: dict, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    abstract_url = body.get("AbstractURL") or ""
    abstract_text = body.get("AbstractText") or ""
    if abstract_text:
        out.append({
            "title": body.get("Heading") or abstract_url,
            "url": abstract_url,
            "snippet": abstract_text,
            "source": "duckduckgo-ia-abstract",
        })
    for topic in body.get("RelatedTopics") or []:
        if "FirstURL" in topic and topic.get("Text"):
            out.append({
                "title": topic["Text"].split(" - ", 1)[0],
                "url": topic["FirstURL"],
                "snippet": topic["Text"],
                "source": "duckduckgo-ia-related",
            })
        elif "Topics" in topic:
            for sub in topic.get("Topics") or []:
                if sub.get("FirstURL") and sub.get("Text"):
                    out.append({
                        "title": sub["Text"].split(" - ", 1)[0],
                        "url": sub["FirstURL"],
                        "snippet": sub["Text"],
                        "source": "duckduckgo-ia-related",
                    })
        if len(out) >= limit:
            break
    return out[:limit]


def _strip_for_fallback(q: str) -> str:
    return _QUOTES_AND_PUNCT.sub(" ", q).strip()


# ---------------------------------------------------------------------------
# per-query caller
# ---------------------------------------------------------------------------


def _query_once(
    q: str, *, session: requests.Session, per_query_limit: int
) -> tuple[str, list[dict[str, str]]]:
    """Run one query through IA → HTML (→ fallback). Returns ``(query, results)``."""
    ia_results: list[dict[str, str]] = []
    html_results: list[dict[str, str]] = []
    try:
        status, body = get_json(
            IA_URL,
            params={"q": q, "format": "json", "no_html": "1", "skip_disambig": "1"},
            session=session,
            timeout=15.0,
        )
        if status < 400 and isinstance(body, dict):
            ia_results = _parse_ia_results(body, limit=per_query_limit)
    except requests.RequestException:
        ia_results = []

    need = per_query_limit - len(ia_results)
    if need > 0:
        try:
            status, html = post_form(
                HTML_URL,
                data={"q": q},
                session=session,
                timeout=15.0,
                headers={"Accept": "text/html", "Referer": "https://html.duckduckgo.com/"},
            )
        except requests.RequestException:
            status, html = 500, ""
        if status >= 400:
            # Fallback: strip quotes + special chars and try once more.
            cleaned = _strip_for_fallback(q)
            if cleaned and cleaned != q:
                try:
                    status, html = post_form(
                        HTML_URL,
                        data={"q": cleaned},
                        session=session,
                        timeout=15.0,
                        headers={"Accept": "text/html",
                                 "Referer": "https://html.duckduckgo.com/"},
                    )
                except requests.RequestException:
                    status, html = 500, ""
        if status < 400 and isinstance(html, str):
            html_results = _parse_html_results(html, limit=need)

    return q, ia_results + html_results


# ---------------------------------------------------------------------------
# fan-out
# ---------------------------------------------------------------------------


def _normalize_queries(
    query: Optional[str], queries: Optional[list[str]]
) -> list[str]:
    raw = list(queries or [])
    if query:
        raw.append(query)
    out: list[str] = []
    seen: set[str] = set()
    for q in raw:
        if not isinstance(q, str):
            continue
        q2 = q.strip()
        if not q2:
            continue
        key = q2.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q2)
    return out[:MAX_QUERIES]


@registry.register(
    name="research.web_search",
    display_name="Web search (DuckDuckGo, parallel fan-out)",
    description=(
        "DuckDuckGo search via the Instant Answer JSON + HTML scrape fallback. "
        "Accepts `queries=[...]` (up to 10) and runs them in parallel via "
        "ThreadPoolExecutor; results are dedup'd by URL across queries. "
        "No API key. On any upstream failure, returns an empty result set "
        "and a clear summary — never fails the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "Use the parallel form when triangulating: "
        "`queries=[\"RFdiffusion3 PPI hotspot tips\", "
        "\"ProteinMPNN soluble model binder design\", "
        "\"pae_interaction filter threshold\"]` — much faster than three "
        "sequential calls. Single-string `query=` still works."
    ),
)
def web_search(
    *,
    query: Optional[str] = None,
    queries: Optional[list[str]] = None,
    limit: int = 10,
    per_query_limit: int = 8,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    qs = _normalize_queries(query, queries)
    if not qs:
        return {
            "summary": "Error: web_search requires `query` or `queries`",
            "error": "invalid_args",
            "metrics": {},
        }

    sess = session or make_session()
    per_query_status: dict[str, str] = {}
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(_query_once, q, session=sess, per_query_limit=per_query_limit) for q in qs]
        for fut in as_completed(futs):
            q, items = fut.result()
            per_query_status[q] = "ok" if items else "empty"
            for item in items:
                url = item.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                # Record which query found it for traceability.
                item["query_origin"] = q
                results.append(item)

    # Source priority: IA-abstract > IA-related > HTML; stable within.
    priority = {
        "duckduckgo-ia-abstract": 0,
        "duckduckgo-ia-related": 1,
        "duckduckgo-html": 2,
    }
    results.sort(key=lambda r: priority.get(r.get("source", ""), 99))
    results = results[:limit]

    if not results:
        return {
            "summary": (
                f"Web search returned nothing useful across {len(qs)} query(s)"
            ),
            "queries_run": qs,
            "per_query_status": per_query_status,
            "results": [],
            "metrics": {"num_queries": len(qs)},
        }
    return {
        "summary": (
            f"Found {len(results)} unique web result(s) across {len(qs)} query(s) "
            f"(after dedup; sources: "
            f"{sum(1 for r in results if r['source'].startswith('duckduckgo-ia'))} IA, "
            f"{sum(1 for r in results if r['source'] == 'duckduckgo-html')} HTML)"
        ),
        "queries_run": qs,
        "per_query_status": per_query_status,
        "results": results,
        "metrics": {
            "num_queries": len(qs),
            "ia_count": sum(1 for r in results if r["source"].startswith("duckduckgo-ia")),
            "html_count": sum(1 for r in results if r["source"] == "duckduckgo-html"),
        },
    }


__all__ = ["web_search"]

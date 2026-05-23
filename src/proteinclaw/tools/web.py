"""``research.web_search`` — DuckDuckGo (Instant Answer + HTML).

No API key required. Strategy:

1. Hit the Instant Answer JSON endpoint — fast, well-formed, but often returns
   only "RelatedTopics" rather than real result links.
2. If IA gives no useful results, fall back to a regex parse of the HTML
   results page (``html.duckduckgo.com``). The HTML is stable enough that a
   tiny parser is worth avoiding the bs4 dependency.

Either failure → graceful degradation (PRD §10.2): empty results, summary
notes the failure, run continues.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session, post_form

IA_URL = "https://api.duckduckgo.com/"
HTML_URL = "https://html.duckduckgo.com/html/"

# Matches DDG result anchors in the HTML view. The structure has been stable
# for years; if DDG redesigns we degrade to "no results" rather than crashing.
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "minLength": 2},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
    },
    "required": ["query"],
}


def _strip_tags(s: str) -> str:
    return _html.unescape(_TAG_RE.sub("", s)).strip()


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG HTML wraps result URLs in /l/?uddg=<encoded>. Unwrap if present."""
    if href.startswith("//duckduckgo.com/l/") or href.startswith("/l/"):
        try:
            parsed = urlparse(href if href.startswith("http") else "https:" + href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        except Exception:  # noqa: BLE001 — never let URL parsing crash a search
            pass
    return href


def _parse_html_results(html: str, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _RESULT_RE.finditer(html):
        href, title_html, snippet_html = m.group(1), m.group(2), m.group(3)
        url = _unwrap_ddg_redirect(href)
        out.append(
            {
                "title": _strip_tags(title_html),
                "url": url,
                "snippet": _strip_tags(snippet_html),
                "source": "duckduckgo-html",
            }
        )
        if len(out) >= limit:
            break
    return out


def _parse_ia_results(body: dict, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    abstract_url = body.get("AbstractURL") or ""
    abstract_text = body.get("AbstractText") or ""
    if abstract_text:
        out.append(
            {
                "title": body.get("Heading") or abstract_url,
                "url": abstract_url,
                "snippet": abstract_text,
                "source": "duckduckgo-ia-abstract",
            }
        )
    for topic in body.get("RelatedTopics") or []:
        # Topics can be either a {Text, FirstURL} dict or a {Name, Topics:[...]} group.
        if "FirstURL" in topic and topic.get("Text"):
            out.append(
                {
                    "title": topic["Text"].split(" - ", 1)[0],
                    "url": topic["FirstURL"],
                    "snippet": topic["Text"],
                    "source": "duckduckgo-ia-related",
                }
            )
        elif "Topics" in topic:
            for sub in topic.get("Topics") or []:
                if sub.get("FirstURL") and sub.get("Text"):
                    out.append(
                        {
                            "title": sub["Text"].split(" - ", 1)[0],
                            "url": sub["FirstURL"],
                            "snippet": sub["Text"],
                            "source": "duckduckgo-ia-related",
                        }
                    )
        if len(out) >= limit:
            break
    return out[:limit]


@registry.register(
    name="research.web_search",
    display_name="Web search (DuckDuckGo)",
    description=(
        "DuckDuckGo search via the Instant Answer JSON + HTML results fallback. "
        "No API key. On any upstream failure, returns an empty result set and a "
        "clear summary — never fails the run."
    ),
    category="research",
    parameters=_PARAMETERS,
    usage_guide=(
        "Use when literature_search comes back empty or for non-paper hints "
        "(blog posts, GitHub issues, parameter tips)."
    ),
)
def web_search(
    *,
    query: str,
    limit: int = 10,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    sess = session or make_session()
    ia_results: list[dict[str, str]] = []
    html_results: list[dict[str, str]] = []

    # 1) Instant Answer — fast and well-formed.
    try:
        status, body = get_json(
            IA_URL,
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
            session=sess,
        )
        if status < 400 and isinstance(body, dict):
            ia_results = _parse_ia_results(body, limit=limit)
    except requests.RequestException:
        ia_results = []

    # 2) HTML scrape — only if we don't have enough from IA. DDG's HTML
    # endpoint expects a POST with form-encoded `q`.
    if len(ia_results) < limit:
        try:
            status, html = post_form(
                HTML_URL,
                data={"q": query},
                session=sess,
                headers={
                    "Accept": "text/html",
                    # DDG html view sometimes rejects empty/missing referer.
                    "Referer": "https://html.duckduckgo.com/",
                },
            )
            if status < 400 and isinstance(html, str):
                html_results = _parse_html_results(html, limit=limit - len(ia_results))
        except requests.RequestException:
            html_results = []

    results = ia_results + html_results

    if not results:
        return {
            "summary": f"Web search unavailable for {query!r} (no results from IA or HTML)",
            "query": query,
            "results": [],
            "metrics": {"ia_count": 0, "html_count": 0},
        }

    return {
        "summary": (
            f"Found {len(results)} web result(s) for {query!r} "
            f"({len(ia_results)} IA + {len(html_results)} HTML)"
        ),
        "query": query,
        "results": results,
        "metrics": {"ia_count": len(ia_results), "html_count": len(html_results)},
    }


__all__ = ["web_search"]

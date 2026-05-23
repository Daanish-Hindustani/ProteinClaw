"""``data.rcsb_search`` — natural-language search of the RCSB PDB.

The primary entry point for *target resolution* (PRD §6.4). Given a free-text
query, returns a ranked list of candidate PDB entries with enough metadata
(resolution, deposition date, structure method, title) for the agent to pick
one — or to surface a clarification menu when multiple distinct entries score
similarly.

Search API: https://search.rcsb.org/#search-api
Data API:   https://data.rcsb.org/#data-api
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session, post_json

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{id}"

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Free-text query (e.g. 'PD-L1 IgV domain').",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 25,
            "default": 5,
            "description": "Max candidate entries to return.",
        },
        "experimental_only": {
            "type": "boolean",
            "default": True,
            "description": "Restrict to experimental structures (exclude CSMs).",
        },
    },
    "required": ["query"],
}


def _build_search_payload(query: str, *, limit: int, experimental_only: bool) -> dict[str, Any]:
    content_types = ["experimental"] if experimental_only else ["experimental", "computational"]
    return {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        "request_options": {
            "results_content_type": content_types,
            "paginate": {"start": 0, "rows": limit},
            "sort": [{"sort_by": "score", "direction": "desc"}],
        },
        "return_type": "entry",
    }


def _fetch_entry_metadata(
    pdb_id: str, session: requests.Session
) -> dict[str, Any]:
    status, payload = get_json(ENTRY_URL.format(id=pdb_id), session=session)
    if status >= 400 or not isinstance(payload, dict):
        return {"pdb_id": pdb_id, "error": f"metadata_http_{status}"}

    title = (payload.get("struct") or {}).get("title") or ""
    methods = payload.get("exptl") or []
    structure_method = methods[0].get("method", "") if methods else ""
    refine = payload.get("refine") or []
    resolution: Optional[float] = None
    if refine and isinstance(refine, list):
        ls_d = refine[0].get("ls_d_res_high")
        if isinstance(ls_d, (int, float)):
            resolution = float(ls_d)
    if resolution is None:
        # Fallback for non-refined / cryo-EM entries.
        cell = payload.get("rcsb_entry_info") or {}
        rb = cell.get("resolution_combined")
        if isinstance(rb, list) and rb:
            resolution = float(rb[0])

    accession = payload.get("rcsb_accession_info") or {}
    deposition_iso = accession.get("deposit_date") or ""

    chains: list[str] = []
    cell = payload.get("rcsb_entry_info") or {}
    polymer_count = cell.get("polymer_entity_count_protein")

    return {
        "pdb_id": pdb_id,
        "title": title,
        "resolution": resolution,
        "structure_method": structure_method,
        "deposition_date": deposition_iso,
        "polymer_protein_count": polymer_count,
        "chains_listed": chains,
    }


def _recency_score(deposition_iso: str) -> float:
    """0..1 score where newer deposition → higher."""
    if not deposition_iso:
        return 0.0
    try:
        dep = datetime.fromisoformat(deposition_iso.rstrip("Z")).replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    now = datetime.now(timezone.utc)
    years = (now - dep).days / 365.25
    # Decay: ~0.97 at 1y, ~0.74 at 10y, ~0.55 at 20y.
    return max(0.0, 1.0 - 0.03 * years) if years >= 0 else 1.0


def _resolution_score(resolution: Optional[float]) -> float:
    if resolution is None:
        return 0.3  # neutral fallback for NMR / non-resolution entries
    if resolution <= 1.5:
        return 1.0
    if resolution <= 2.5:
        return 0.85
    if resolution <= 3.5:
        return 0.6
    return 0.3


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for c in candidates:
        rs = _resolution_score(c.get("resolution"))
        recency = _recency_score(c.get("deposition_date") or "")
        # Search-score weight kept low so it can't trump real structural quality.
        search_score = float(c.get("search_score", 0.0))
        c["rank_score"] = round(0.5 * rs + 0.3 * recency + 0.2 * min(search_score, 1.0), 4)
    candidates.sort(key=lambda c: c["rank_score"], reverse=True)
    return candidates


@registry.register(
    name="data.rcsb_search",
    display_name="RCSB structure search",
    description=(
        "Free-text search of the RCSB PDB. Returns ranked candidate entries with "
        "resolution, deposition date, method, and title. For target resolution, "
        "the agent should inspect `requires_clarification` and the top candidates "
        "before passing one to `data.pdb_fetch`."
    ),
    category="data",
    parameters=_PARAMETERS,
    usage_guide=(
        "Phrase the query with both the target name AND the domain when known "
        "(e.g. 'PD-L1 IgV domain'). Top result is the ranked best pick; "
        "`requires_clarification=True` means ≥2 candidates returned."
    ),
)
def rcsb_search(
    *,
    query: str,
    limit: int = 5,
    experimental_only: bool = True,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    sess = session or make_session()
    payload = _build_search_payload(query, limit=limit, experimental_only=experimental_only)
    status, body = post_json(SEARCH_URL, payload=payload, session=sess)

    if status == 204 or (isinstance(body, dict) and not body.get("result_set")):
        return {
            "summary": f"No RCSB entries matched {query!r}",
            "query": query,
            "candidates": [],
            "requires_clarification": False,
            "metrics": {"http_status": status, "num_results": 0},
        }
    if status >= 400 or not isinstance(body, dict):
        return {
            "summary": f"Error: RCSB search returned HTTP {status}",
            "error": "upstream_error",
            "metrics": {"http_status": status},
        }

    raw = body.get("result_set") or []
    candidates: list[dict[str, Any]] = []
    for r in raw[:limit]:
        pid = r.get("identifier")
        if not pid:
            continue
        meta = _fetch_entry_metadata(pid, sess)
        meta["search_score"] = float(r.get("score") or 0.0)
        candidates.append(meta)

    candidates = _rank_candidates(candidates)

    summary = (
        f"{len(candidates)} RCSB candidate(s) for {query!r}; "
        f"top: {candidates[0]['pdb_id']} ({candidates[0].get('title', '')[:60]})"
        if candidates
        else f"No usable RCSB candidates for {query!r}"
    )
    return {
        "summary": summary,
        "query": query,
        "candidates": candidates,
        "requires_clarification": len(candidates) > 1,
        "metrics": {"http_status": status, "num_results": len(candidates)},
    }


__all__ = ["rcsb_search"]

"""``data.uniprot_fetch`` — look up a protein in UniProt.

Accepts either a UniProt accession (``P12345``) or a human-readable name
(``PD-L1``). Accessions are fetched directly; names go through the search
endpoint and are flagged ``requires_clarification`` when multiple distinct
candidates come back.

API docs: https://rest.uniprot.org/
"""

from __future__ import annotations

import re
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_json, make_session

# Official UniProt accession regex (https://www.uniprot.org/help/accession_numbers).
_ACCESSION_RE = re.compile(r"^[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$")

UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "UniProt accession (e.g. P12345) or protein/gene name.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 25,
            "default": 5,
            "description": "Max candidates to return for name searches.",
        },
        "organism": {
            "type": "string",
            "description": "Optional organism filter (e.g. 'Homo sapiens') for name searches.",
        },
    },
    "required": ["query"],
}


def _looks_like_accession(s: str) -> bool:
    return bool(_ACCESSION_RE.match(s.strip().upper()))


def _extract_domains(entry: dict[str, Any]) -> list[dict[str, Any]]:
    domains: list[dict[str, Any]] = []
    for feat in entry.get("features", []) or []:
        if feat.get("type") != "Domain":
            continue
        loc = feat.get("location", {}) or {}
        start = (loc.get("start") or {}).get("value")
        end = (loc.get("end") or {}).get("value")
        domains.append(
            {
                "name": feat.get("description") or "(unnamed domain)",
                "start": start,
                "end": end,
            }
        )
    return domains


def _entry_to_summary(entry: dict[str, Any]) -> dict[str, Any]:
    accession = entry.get("primaryAccession", "")
    desc = entry.get("proteinDescription", {}) or {}
    name_block = desc.get("recommendedName") or {}
    protein_name = (name_block.get("fullName") or {}).get("value") or entry.get(
        "uniProtkbId", ""
    )
    organism = (entry.get("organism") or {}).get("scientificName") or ""
    sequence = (entry.get("sequence") or {}).get("value") or ""
    return {
        "accession": accession,
        "protein_name": protein_name,
        "organism": organism,
        "sequence": sequence,
        "length": len(sequence),
        "domains": _extract_domains(entry),
    }


def _fetch_by_accession(
    accession: str, session: Optional[requests.Session]
) -> dict[str, Any]:
    url = f"{UNIPROT_BASE}/{accession}"
    status, payload = get_json(url, session=session)
    if status == 404:
        return {
            "summary": f"Error: UniProt accession {accession!r} not found",
            "error": "invalid_query",
            "metrics": {"http_status": 404},
        }
    if status >= 400:
        return {
            "summary": f"Error: UniProt returned HTTP {status}",
            "error": "upstream_error",
            "metrics": {"http_status": status},
        }
    if not isinstance(payload, dict):
        return {
            "summary": "Error: UniProt returned a non-JSON payload",
            "error": "upstream_error",
            "metrics": {"http_status": status},
        }
    entry = _entry_to_summary(payload)
    return {
        "summary": (
            f"Found UniProt {entry['accession']} ({entry['protein_name']}, "
            f"{entry['organism']}, {entry['length']} aa, {len(entry['domains'])} domain(s))"
        ),
        "metrics": {"http_status": status},
        **entry,
    }


def _search_by_name(
    query: str,
    *,
    limit: int,
    organism: Optional[str],
    session: Optional[requests.Session],
) -> dict[str, Any]:
    q = query
    if organism:
        q = f'{query} AND organism_name:"{organism}"'
    params = {
        "query": q,
        "format": "json",
        "size": str(limit),
        "fields": (
            "accession,id,protein_name,organism_name,sequence,ft_domain,length"
        ),
    }
    url = f"{UNIPROT_BASE}/search"
    status, payload = get_json(url, params=params, session=session)
    if status >= 400 or not isinstance(payload, dict):
        return {
            "summary": f"Error: UniProt search returned HTTP {status}",
            "error": "upstream_error",
            "metrics": {"http_status": status},
        }
    results = payload.get("results") or []
    if not results:
        return {
            "summary": f"No UniProt entries matched {query!r}",
            "error": "invalid_query",
            "metrics": {"http_status": status, "num_results": 0},
        }
    candidates = [_entry_to_summary(r) for r in results]
    # Single match → treat as resolved.
    if len(candidates) == 1:
        c = candidates[0]
        return {
            "summary": (
                f"Found UniProt {c['accession']} ({c['protein_name']}, "
                f"{c['organism']}, {c['length']} aa)"
            ),
            "metrics": {"http_status": status, "num_results": 1},
            **c,
        }
    return {
        "summary": (
            f"{len(candidates)} UniProt candidates for {query!r} — clarification needed"
        ),
        "requires_clarification": True,
        "candidates": candidates,
        "metrics": {"http_status": status, "num_results": len(candidates)},
    }


@registry.register(
    name="data.uniprot_fetch",
    display_name="UniProt fetch",
    description=(
        "Look up a protein in UniProt by accession (e.g. P12345) or name (e.g. PD-L1). "
        "Returns sequence, organism, and domain annotations. For ambiguous names, "
        "returns multiple candidates with `requires_clarification: true` so the agent "
        "can ask the user."
    ),
    category="data",
    parameters=_PARAMETERS,
    usage_guide=(
        "Prefer accessions when known. For names, pass an `organism` filter "
        "(e.g. 'Homo sapiens') to reduce ambiguity."
    ),
)
def uniprot_fetch(
    *,
    query: str,
    limit: int = 5,
    organism: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    sess = session or make_session()
    if _looks_like_accession(query):
        return _fetch_by_accession(query.strip().upper(), sess)
    return _search_by_name(query.strip(), limit=limit, organism=organism, session=sess)


__all__ = ["uniprot_fetch"]

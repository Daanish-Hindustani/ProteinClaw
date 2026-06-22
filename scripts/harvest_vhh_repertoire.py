"""Harvest a natural VHH (nanobody) repertoire from the PDB via RCSB.

Full-text search for nanobody/VHH polymer entities → batch-fetch sequences via
the RCSB GraphQL data API → keep only chains that parse as a VHH domain (using
the same anchor numbering as the library tool) → dedup → write a FASTA.

Output: data/natural_vhh_repertoire.fasta (real, deposited camelid VHH domains).
Run: python scripts/harvest_vhh_repertoire.py [max_seqs]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

from proteinclaw.tools.nanobody_library import _number_vhh_cdrs, _trim_vhh_domain

SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
GRAPHQL = "https://data.rcsb.org/graphql"
_CAMELID = ("camelus", "lama", "vicugna", "camelid")


def _search_entity_ids(rows: int = 5000) -> list[str]:
    q = {
        "query": {
            "type": "terminal", "service": "full_text",
            "parameters": {"value": "nanobody"},
        },
        "return_type": "polymer_entity",
        "request_options": {"return_all_hits": True},
    }
    r = requests.get(SEARCH, params={"json": json.dumps(q)}, timeout=120)
    r.raise_for_status()
    return [hit["identifier"] for hit in r.json().get("result_set", [])]


def _fetch_sequences(entity_ids: list[str]) -> list[tuple[str, str, str]]:
    """Return (entity_id, organism, sequence) for each entity, batched via GraphQL."""
    out: list[tuple[str, str, str]] = []
    query = """
    query($ids:[String!]!){ polymer_entities(entity_ids:$ids){
      rcsb_id
      entity_poly { pdbx_seq_one_letter_code_can }
      rcsb_entity_source_organism { scientific_name }
    }}"""
    for i in range(0, len(entity_ids), 50):
        chunk = entity_ids[i : i + 50]
        r = requests.post(GRAPHQL, json={"query": query, "variables": {"ids": chunk}}, timeout=60)
        if r.status_code != 200:
            continue
        for e in (r.json().get("data") or {}).get("polymer_entities") or []:
            if not e:
                continue
            seq = ((e.get("entity_poly") or {}).get("pdbx_seq_one_letter_code_can") or "").upper()
            orgs = e.get("rcsb_entity_source_organism") or []
            org = (orgs[0].get("scientific_name") if orgs else "") or ""
            out.append((e.get("rcsb_id", "?"), org, seq))
        time.sleep(0.2)
    return out


def main() -> None:
    max_seqs = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    ids = _search_entity_ids()
    print(f"search returned {len(ids)} polymer entities")
    rows = _fetch_sequences(ids)
    print(f"fetched {len(rows)} sequences")

    seen: set[str] = set()
    kept: list[tuple[str, str]] = []
    for eid, org, raw in rows:
        if not raw or not (100 <= len(raw) <= 160):
            continue
        seq = _trim_vhh_domain(raw)
        if not (105 <= len(seq) <= 140):
            continue
        if _number_vhh_cdrs(seq) is None:  # must parse as a VHH domain
            continue
        # prefer camelid, but accept any chain that is structurally a VHH
        if seq in seen:
            continue
        seen.add(seq)
        camelid = any(c in org.lower() for c in _CAMELID)
        kept.append((f"{eid}|{org or 'unknown'}{'|camelid' if camelid else ''}", seq))
        if len(kept) >= max_seqs:
            break

    out_path = Path(__file__).resolve().parent.parent / "data" / "natural_vhh_repertoire.fasta"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text("".join(f">{h}\n{s}\n" for h, s in kept))
    n_camelid = sum(1 for h, _ in kept if "camelid" in h)
    print(f"wrote {len(kept)} VHH domains ({n_camelid} camelid-annotated) → {out_path}")


if __name__ == "__main__":
    main()

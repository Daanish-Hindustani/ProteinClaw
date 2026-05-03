"""HTTP clients for protein-design knowledge sources."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx


PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
RCSB_CIF_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
RCSB_PDB_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"


def _get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        if not response.content or not response.text.strip():
            return {}
        return response.json()


def _get_text(url: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.text


def build_pubmed_query_variants(
    query: str,
    *,
    date_range: str = "",
    article_types: list[str] | None = None,
) -> list[str]:
    base = " ".join(query.split())
    variants = [
        base,
        f'"{base}"',
        f"({base}) AND review[Publication Type]",
        f"({base}) AND protein design",
        f"({base}) AND structure OR binding OR enzyme",
    ]
    if date_range:
        variants = [f"({v}) AND {date_range}" for v in variants]
    for article_type in article_types or []:
        clean = str(article_type).strip()
        if clean:
            variants.append(f"({base}) AND {clean}[Publication Type]")
    deduped: list[str] = []
    for item in variants:
        if item not in deduped:
            deduped.append(item)
    return deduped


def search_pubmed(
    query: str,
    *,
    max_results: int = 20,
    date_range: str = "",
    article_types: list[str] | None = None,
    query_variations: bool = True,
) -> dict[str, Any]:
    variants = (
        build_pubmed_query_variants(query, date_range=date_range, article_types=article_types)
        if query_variations
        else [query]
    )
    api_key = os.getenv("NCBI_API_KEY") or os.getenv("HERMES_PROTEIN_NCBI_API_KEY")
    email = os.getenv("NCBI_TOOL_EMAIL") or os.getenv("HERMES_PROTEIN_NCBI_EMAIL")
    ids: list[str] = []
    seen: set[str] = set()
    per_query: list[dict[str, Any]] = []

    for variant in variants:
        params = {
            "db": "pubmed",
            "term": variant,
            "retmode": "json",
            "retmax": max(1, min(max_results, 100)),
            "sort": "relevance",
        }
        if api_key:
            params["api_key"] = api_key
        if email:
            params["email"] = email
        data = _get_json(f"{PUBMED_BASE}/esearch.fcgi", params=params)
        found = data.get("esearchresult", {}).get("idlist", []) or []
        per_query.append({"query": variant, "count": len(found)})
        for pmid in found:
            if pmid not in seen:
                seen.add(pmid)
                ids.append(pmid)
            if len(ids) >= max_results:
                break
        if len(ids) >= max_results:
            break

    papers = fetch_pubmed_records(ids)
    return {"query": query, "query_variants": variants, "per_query": per_query, "results": papers}


def fetch_pubmed_records(pmids: list[str]) -> list[dict[str, Any]]:
    if not pmids:
        return []
    xml_text = _get_text(
        f"{PUBMED_BASE}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
    )
    root = ET.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        article_node = medline.find("Article") if medline is not None else None
        pmid = (medline.findtext("PMID") if medline is not None else "") or ""
        title = "".join(article_node.findtext("ArticleTitle") or "").strip() if article_node is not None else ""
        abstract = " ".join(
            " ".join(node.itertext()).strip()
            for node in article.findall(".//AbstractText")
            if " ".join(node.itertext()).strip()
        )
        authors = []
        for author in article.findall(".//Author"):
            last = author.findtext("LastName") or ""
            initials = author.findtext("Initials") or ""
            collective = author.findtext("CollectiveName") or ""
            name = collective or " ".join(part for part in (last, initials) if part)
            if name:
                authors.append(name)
        doi = ""
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = aid.text or ""
                break
        journal = article.findtext(".//Journal/Title") or article.findtext(".//ISOAbbreviation") or ""
        year = article.findtext(".//PubDate/Year") or ""
        mesh_terms = [mh.findtext("DescriptorName") for mh in article.findall(".//MeshHeading")]
        results.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "mesh_terms": [m for m in mesh_terms if m],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        })
    return results


def search_uniprot(
    query: str,
    *,
    organism_id: str = "",
    gene: str = "",
    reviewed_only: bool = True,
    max_results: int = 25,
    include_sequence: bool = True,
) -> dict[str, Any]:
    clauses = [f"({query})"]
    if organism_id:
        clauses.append(f"(organism_id:{organism_id})")
    if gene:
        clauses.append(f"(gene:{gene})")
    if reviewed_only:
        clauses.append("(reviewed:true)")
    fields = [
        "accession", "id", "protein_name", "gene_names", "organism_name",
        "length", "cc_function", "ft_domain", "xref_pdb",
    ]
    if include_sequence:
        fields.append("sequence")
    params = {
        "query": " AND ".join(clauses),
        "format": "json",
        "fields": ",".join(fields),
        "size": max(1, min(max_results, 100)),
    }
    data = _get_json(UNIPROT_SEARCH_URL, params=params)
    return {
        "query": query,
        "results": [normalize_uniprot_entry(item) for item in data.get("results", [])],
    }


def normalize_uniprot_entry(item: dict[str, Any]) -> dict[str, Any]:
    genes = []
    for gene in item.get("genes", []) or []:
        name = (gene.get("geneName") or {}).get("value")
        if name:
            genes.append(name)
    comments = []
    for comment in item.get("comments", []) or []:
        if comment.get("commentType") == "FUNCTION":
            texts = [t.get("value", "") for t in comment.get("texts", [])]
            comments.extend(t for t in texts if t)
    features = [
        {
            "type": f.get("type"),
            "description": f.get("description"),
            "location": f.get("location"),
        }
        for f in item.get("features", []) or []
    ]
    pdb_refs = [
        x.get("id")
        for x in item.get("uniProtKBCrossReferences", []) or []
        if x.get("database") == "PDB" and x.get("id")
    ]
    return {
        "accession": item.get("primaryAccession"),
        "id": item.get("uniProtkbId"),
        "protein_name": (((item.get("proteinDescription") or {}).get("recommendedName") or {}).get("fullName") or {}).get("value"),
        "genes": genes,
        "organism": (item.get("organism") or {}).get("scientificName"),
        "length": (item.get("sequence") or {}).get("length"),
        "sequence": (item.get("sequence") or {}).get("value"),
        "function": " ".join(comments),
        "features": features,
        "pdb_refs": pdb_refs,
    }


def search_rcsb(
    query: str,
    *,
    search_type: str = "text",
    max_results: int = 25,
    return_type: str = "entry",
    download: bool = False,
    output_dir: str = "",
    download_format: str = "cif",
    pdb_ids: list[str] | None = None,
) -> dict[str, Any]:
    direct_ids = normalize_pdb_ids(pdb_ids)
    if direct_ids:
        identifiers = direct_ids[:max_results]
    else:
        payload = build_rcsb_query(query, search_type=search_type, return_type=return_type, max_results=max_results)
        data = _get_json(RCSB_SEARCH_URL, params={"json": json.dumps(payload)})
        identifiers = [item.get("identifier") for item in data.get("result_set", []) if item.get("identifier")]
    entries = []
    for ident in identifiers[:max_results]:
        pdb_id = ident.split("_")[0].split(".")[0].split("-")[0].upper()
        entry = {"identifier": ident, "pdb_id": pdb_id}
        try:
            meta = _get_json(RCSB_DATA_ENTRY_URL.format(pdb_id=pdb_id))
            entry.update(normalize_rcsb_entry(meta))
        except Exception as exc:
            entry["metadata_error"] = str(exc)
        if download:
            target_dir = Path(output_dir or "protein_design_rcsb").expanduser().resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            fmt = download_format.lower().strip()
            if fmt not in {"cif", "pdb"}:
                fmt = "cif"
            url = RCSB_PDB_URL if fmt == "pdb" else RCSB_CIF_URL
            structure_path = target_dir / f"{pdb_id}.{fmt}"
            structure_path.write_text(_get_text(url.format(pdb_id=pdb_id)), encoding="utf-8")
            entry["local_path"] = str(structure_path)
            entry["download_format"] = fmt
            entry["chains"] = summarize_structure_chains(structure_path)
        entries.append(entry)
    return {"query": query, "search_type": "pdb_id" if direct_ids else search_type, "pdb_ids": direct_ids, "results": entries}


def normalize_pdb_ids(pdb_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in pdb_ids or []:
        for item in str(raw).replace(",", " ").split():
            pdb_id = item.strip().upper()
            if re.fullmatch(r"[0-9][A-Z0-9]{3}", pdb_id) and pdb_id not in normalized:
                normalized.append(pdb_id)
    return normalized


def build_rcsb_query(query: str, *, search_type: str, return_type: str, max_results: int) -> dict[str, Any]:
    if search_type == "sequence":
        node = {
            "type": "terminal",
            "service": "sequence",
            "parameters": {
                "evalue_cutoff": 1,
                "identity_cutoff": 0.3,
                "sequence_type": "protein",
                "value": query,
            },
        }
    elif search_type == "uniprot":
        node = {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                "operator": "exact_match",
                "value": query,
            },
        }
    elif search_type == "ligand":
        node = {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_nonpolymer_entity_container_identifiers.nonpolymer_comp_id",
                "operator": "exact_match",
                "value": query.upper(),
            },
        }
    else:
        node = {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        }
    return {
        "query": node,
        "return_type": return_type,
        "request_options": {"paginate": {"start": 0, "rows": max(1, min(max_results, 100))}},
    }


def normalize_rcsb_entry(meta: dict[str, Any]) -> dict[str, Any]:
    citation = (meta.get("citation") or [{}])[0]
    methods = [m.get("method") for m in meta.get("exptl", []) or [] if m.get("method")]
    resolution = None
    for refine in meta.get("refine", []) or []:
        if refine.get("ls_d_res_high") is not None:
            resolution = refine.get("ls_d_res_high")
            break
    return {
        "title": (meta.get("struct") or {}).get("title"),
        "experimental_methods": methods,
        "resolution": resolution,
        "release_date": ((meta.get("rcsb_accession_info") or {}).get("initial_release_date")),
        "doi": citation.get("pdbx_database_id_DOI"),
        "pubmed_id": citation.get("pdbx_database_id_PubMed"),
    }


def parse_pdb_residues(path: Path) -> dict[str, set[int]]:
    """Parse chain/residue IDs from legacy PDB ATOM/HETATM records."""
    residues: dict[str, set[int]] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("ATOM  "):
                continue
            chain = (line[21].strip() or "_")
            try:
                resi = int(line[22:26].strip())
            except ValueError:
                continue
            residues.setdefault(chain, set()).add(resi)
    return residues


def _add_hetatm_record(records: dict[str, dict[str, Any]], comp_id: str, chain: str, resi: int) -> None:
    key = f"{comp_id}:{chain}:{resi}"
    record = records.setdefault(key, {"comp_id": comp_id, "chain": chain, "residue_number": resi, "atom_count": 0})
    record["atom_count"] += 1


def parse_pdb_hetatm_records(path: Path) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("HETATM"):
                continue
            comp_id = line[17:20].strip() or "UNK"
            chain = line[21].strip() or "_"
            try:
                resi = int(line[22:26].strip())
            except ValueError:
                continue
            _add_hetatm_record(records, comp_id, chain, resi)
    return sorted(records.values(), key=lambda item: (item["chain"], item["residue_number"], item["comp_id"]))


def parse_pdb_resolution(path: Path) -> float | None:
    pattern = re.compile(r"RESOLUTION\.\s+([0-9.]+)\s+ANGSTROMS", re.IGNORECASE)
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("REMARK   2"):
                continue
            match = pattern.search(line)
            if match:
                return float(match.group(1))
    return None


def parse_mmcif_residues(path: Path) -> dict[str, set[int]]:
    """Parse chain/residue IDs from mmCIF _atom_site loops.

    This intentionally handles only the columns needed for design setup. It
    uses auth IDs when available because those normally match residue labels
    users see in structure viewers and PDB-derived design specs.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    residues: dict[str, set[int]] = {}
    idx = 0
    while idx < len(lines):
        if lines[idx].strip() != "loop_":
            idx += 1
            continue
        idx += 1
        fields: list[str] = []
        while idx < len(lines) and lines[idx].strip().startswith("_atom_site."):
            fields.append(lines[idx].strip())
            idx += 1
        if not fields:
            continue
        if "_atom_site.group_PDB" not in fields:
            continue
        chain_field = "_atom_site.auth_asym_id" if "_atom_site.auth_asym_id" in fields else "_atom_site.label_asym_id"
        seq_field = "_atom_site.auth_seq_id" if "_atom_site.auth_seq_id" in fields else "_atom_site.label_seq_id"
        try:
            group_i = fields.index("_atom_site.group_PDB")
            chain_i = fields.index(chain_field)
            seq_i = fields.index(seq_field)
        except ValueError:
            continue
        while idx < len(lines):
            raw = lines[idx].strip()
            if not raw or raw == "#" or raw == "loop_" or raw.startswith("_"):
                break
            parts = raw.split()
            if len(parts) > max(group_i, chain_i, seq_i) and parts[group_i] == "ATOM":
                chain = parts[chain_i].strip("'\"") or "_"
                try:
                    resi = int(float(parts[seq_i].strip("'\"")))
                except ValueError:
                    idx += 1
                    continue
                residues.setdefault(chain, set()).add(resi)
            idx += 1
    return residues


def _iter_mmcif_atom_rows(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    idx = 0
    while idx < len(lines):
        if lines[idx].strip() != "loop_":
            idx += 1
            continue
        idx += 1
        fields: list[str] = []
        while idx < len(lines) and lines[idx].strip().startswith("_atom_site."):
            fields.append(lines[idx].strip())
            idx += 1
        if not fields or "_atom_site.group_PDB" not in fields:
            continue
        while idx < len(lines):
            raw = lines[idx].strip()
            if not raw or raw == "#" or raw == "loop_" or raw.startswith("_"):
                break
            parts = raw.split()
            if len(parts) >= len(fields):
                yield fields, parts
            idx += 1


def parse_mmcif_hetatm_records(path: Path) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for fields, parts in _iter_mmcif_atom_rows(path):
        try:
            group_i = fields.index("_atom_site.group_PDB")
            comp_i = fields.index("_atom_site.auth_comp_id" if "_atom_site.auth_comp_id" in fields else "_atom_site.label_comp_id")
            chain_i = fields.index("_atom_site.auth_asym_id" if "_atom_site.auth_asym_id" in fields else "_atom_site.label_asym_id")
            seq_i = fields.index("_atom_site.auth_seq_id" if "_atom_site.auth_seq_id" in fields else "_atom_site.label_seq_id")
        except ValueError:
            continue
        if parts[group_i] != "HETATM":
            continue
        try:
            resi = int(float(parts[seq_i].strip("'\"")))
        except ValueError:
            continue
        _add_hetatm_record(records, parts[comp_i].strip("'\"") or "UNK", parts[chain_i].strip("'\"") or "_", resi)
    return sorted(records.values(), key=lambda item: (item["chain"], item["residue_number"], item["comp_id"]))


def parse_mmcif_resolution(path: Path) -> float | None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("_refine.ls_d_res_high"):
            parts = stripped.split()
            value = parts[1] if len(parts) > 1 else (lines[idx + 1].strip() if idx + 1 < len(lines) else "")
            try:
                return float(value.strip("'\""))
            except ValueError:
                return None
    return None


def summarize_residues(residues: dict[str, set[int]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for chain, values in sorted(residues.items()):
        ordered = sorted(values)
        if not ordered:
            continue
        gaps = [resi for resi in range(ordered[0], ordered[-1] + 1) if resi not in values]
        ranges: list[str] = []
        start = prev = ordered[0]
        for resi in ordered[1:]:
            if resi == prev + 1:
                prev = resi
                continue
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = resi
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        summary[chain] = {
            "count": len(ordered),
            "range": f"{ordered[0]}-{ordered[-1]}",
            "continuous_ranges": ranges,
            "gaps": gaps,
        }
    return summary


def summarize_structure_chains(path: Path) -> dict[str, dict[str, Any]]:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".pdb") or suffixes.endswith(".ent"):
        return summarize_residues(parse_pdb_residues(path))
    if suffixes.endswith(".cif") or suffixes.endswith(".mmcif"):
        return summarize_residues(parse_mmcif_residues(path))
    return {}


def inspect_structure_file(path: Path) -> dict[str, Any]:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".pdb") or suffixes.endswith(".ent"):
        fmt = "pdb"
        chains = summarize_residues(parse_pdb_residues(path))
        hetatm_records = parse_pdb_hetatm_records(path)
        resolution = parse_pdb_resolution(path)
    elif suffixes.endswith(".cif") or suffixes.endswith(".mmcif"):
        fmt = "cif"
        chains = summarize_residues(parse_mmcif_residues(path))
        hetatm_records = parse_mmcif_hetatm_records(path)
        resolution = parse_mmcif_resolution(path)
    else:
        raise ValueError(f"Unsupported structure format: {path}")
    return {
        "path": str(path),
        "format": fmt,
        "resolution": resolution,
        "chains": chains,
        "hetatm_records": hetatm_records,
        "hetatm_comp_ids": sorted({record["comp_id"] for record in hetatm_records}),
    }

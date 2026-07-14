"""Deterministic interface-quality metrics for a predicted binder+target complex.

Pure biopython (no registry/SDK imports) so BOTH the ``analysis.interface_metrics``
MCP tool and post-run triage can call ``compute_interface_metrics`` on an AF2
complex PDB (binder = chain A, target = chain B, per the AF2 wrapper convention).

These are **QC / sanity** metrics — the de-novo binder field treats hotspot
satisfaction, contacts, clashes and geometry as sanity checks, and BSA as a
size normalizer; they **augment, never replace** the ``complex_confidence`` +
ipSAE ranking. KD (untrustworthy from a predicted designed complex) and Rosetta
ddG (heavy PyRosetta dep) are deliberately NOT computed here — see the plan.
"""

from __future__ import annotations

import copy
import json
import math
import statistics
from pathlib import Path
from typing import Any, Optional

# Bondi (1964) van der Waals radii (Å) for common heavy atoms.
_VDW = {"C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80, "P": 1.80, "F": 1.47, "CL": 1.75}
_DEFAULT_VDW = 1.70

_CONTACT_HEAVY_CUTOFF = 4.5   # heavy-atom inter-chain contact (CAPRI standard)
_CLASH_OVERLAP = 0.4          # MolProbity: overlap past (VdW_i + VdW_j) − 0.4 Å
# We model no explicit hydrogens, so legitimate H-bonds / salt bridges sit at
# short heavy-atom distances. Mirror MolProbity's H-bond allowance: relax the
# clash cutoff for N/O donor–acceptor pairs so a real H-bond (~2.7–3.0 Å) isn't
# flagged, while genuine sub-VdW overlaps still are.
_HBOND_ALLOWANCE = 0.5
_HBOND_ELEMENTS = {"N", "O"}
_HOTSPOT_CB_CUTOFF = 8.0      # Cβ–Cβ cutoff for "hotspot contacted" (RFdiffusion convention)
_HOTSPOT_HEAVY_CUTOFF = 5.0   # heavy-atom alternative
_AFM_CA_CONTACT_CUTOFF = 10.0  # MRGPRX2 AF-M screen residue-pair contact definition


class InterfaceMetricsError(ValueError):
    """Raised for unrecoverable input problems (missing file/chain)."""


def _standard_residues(chain) -> list:
    """Protein residues only (drop waters/HETATM — id hetflag is blank for ATOM)."""
    return [r for r in chain if r.id[0] == " "]


def _heavy_atoms(residues) -> list:
    return [a for a in (atom for res in residues for atom in res) if a.element != "H"]


def _cb(residue):
    """Cβ if present, else Cα (Gly), else None."""
    if "CB" in residue:
        return residue["CB"]
    if "CA" in residue:
        return residue["CA"]
    return None


def _load_two_chains(complex_pdb: str, binder_chain: str, target_chain: str):
    from Bio.PDB import MMCIFParser, PDBParser

    path = Path(complex_pdb)
    if not path.exists():
        raise InterfaceMetricsError(f"complex PDB not found: {complex_pdb}")
    parser = MMCIFParser(QUIET=True) if path.suffix.lower() in {".cif", ".mmcif"} else PDBParser(QUIET=True)
    model = parser.get_structure("cx", str(path))[0]
    for cid in (binder_chain, target_chain):
        if cid not in model:
            raise InterfaceMetricsError(
                f"chain {cid!r} not in complex (have: {[c.id for c in model]})"
            )
    return model


def _interface_contacts(binder_res, target_res) -> dict[str, Any]:
    from Bio.PDB import NeighborSearch

    t_atoms = _heavy_atoms(target_res)
    ns = NeighborSearch(t_atoms)
    pairs: set[tuple] = set()
    iface_binder: set = set()
    iface_target: set = set()
    for res in binder_res:
        for atom in (a for a in res if a.element != "H"):
            for near in ns.search(atom.coord, _CONTACT_HEAVY_CUTOFF, level="A"):
                tr = near.get_parent()
                pairs.add((res.id[1], tr.id[1]))
                iface_binder.add(res.id[1])
                iface_target.add(tr.id[1])
    return {
        "n_contacts": len(pairs),
        "iface_binder": iface_binder,
        "iface_target": iface_target,
    }


def _chain_only_model(model, keep: str):
    m = copy.deepcopy(model)
    for ch in list(m):
        if ch.id != keep:
            m.detach_child(ch.id)
    # strip non-standard residues so SASA only sees the protein
    for ch in m:
        for res in [r for r in ch if r.id[0] != " "]:
            ch.detach_child(res.id)
    return m


def _two_chain_model(model, a: str, b: str):
    m = copy.deepcopy(model)
    for ch in list(m):
        if ch.id not in (a, b):
            m.detach_child(ch.id)
    for ch in m:
        for res in [r for r in ch if r.id[0] != " "]:
            ch.detach_child(res.id)
    return m


def _total_sasa(entity) -> float:
    from Bio.PDB.SASA import ShrakeRupley

    ShrakeRupley(probe_radius=1.4, n_points=100).compute(entity, level="A")
    return float(sum(a.sasa for a in entity.get_atoms()))


def _interface_bsa(model, binder_chain: str, target_chain: str) -> float:
    """ΔSASA = SASA(binder) + SASA(target) − SASA(complex), in Å²."""
    sasa_b = _total_sasa(_chain_only_model(model, binder_chain))
    sasa_t = _total_sasa(_chain_only_model(model, target_chain))
    sasa_complex = _total_sasa(_two_chain_model(model, binder_chain, target_chain))
    return round(sasa_b + sasa_t - sasa_complex, 1)


def _clash_score(model, binder_chain: str, target_chain: str) -> dict[str, Any]:
    """MolProbity-style: heavy-atom pairs overlapping > 0.4 Å past VdW sum,
    per 1000 atoms. Excludes same-residue and sequential-backbone pairs."""
    from Bio.PDB import NeighborSearch

    atoms = [
        a
        for cid in (binder_chain, target_chain)
        for a in _heavy_atoms(_standard_residues(model[cid]))
    ]
    if not atoms:
        return {"clash_score": 0.0, "n_clashes": 0}
    ns = NeighborSearch(atoms)
    # Max meaningful pair distance: largest VdW sum (S+S=3.6) minus overlap.
    clashes = 0
    seen: set = set()
    for a1, a2 in ns.search_all(3.6, level="A"):
        r1, r2 = a1.get_parent(), a2.get_parent()
        if r1 is r2:
            continue
        # skip sequential backbone neighbours in the same chain
        if r1.get_parent().id == r2.get_parent().id and abs(r1.id[1] - r2.id[1]) <= 1:
            continue
        e1, e2 = a1.element, a2.element
        # S–S contacts at this range are disulfide bonds, not clashes.
        if e1 == "S" and e2 == "S":
            continue
        key = tuple(sorted((id(a1), id(a2))))
        if key in seen:
            continue
        seen.add(key)
        # H-bond / salt-bridge allowance for N/O donor–acceptor pairs (no
        # explicit H to model the bond) — see _HBOND_ALLOWANCE.
        allowance = _HBOND_ALLOWANCE if (e1 in _HBOND_ELEMENTS and e2 in _HBOND_ELEMENTS) else 0.0
        vdw = _VDW.get(e1, _DEFAULT_VDW) + _VDW.get(e2, _DEFAULT_VDW)
        if (a1 - a2) < vdw - _CLASH_OVERLAP - allowance:
            clashes += 1
    return {"clash_score": round(clashes / len(atoms) * 1000, 2), "n_clashes": clashes}


def _contact_geometry(binder_res, target_res, iface_binder: set, iface_target: set) -> dict[str, Any]:
    def _com(residues, ids):
        cas = [r["CA"].coord for r in residues if r.id[1] in ids and "CA" in r]
        if not cas:
            return None
        return [sum(c[i] for c in cas) / len(cas) for i in range(3)]

    com_b = _com(binder_res, iface_binder)
    com_t = _com(target_res, iface_target)
    com_dist = None
    if com_b and com_t:
        com_dist = round(math.dist(com_b, com_t), 2)
    return {
        "n_res_binder": len(iface_binder),
        "n_res_target": len(iface_target),
        "com_distance": com_dist,
    }


def _hotspot_satisfaction(
    binder_res, target_chain, hotspots: list[str], crop_start: Optional[int]
) -> dict[str, Any]:
    """Fraction of RFD3 hotspots the binder contacts (Cβ ≤ 8 Å or heavy ≤ 5 Å).

    RFD3 hotspots are numbered on the *cropped target* (e.g. ``A23``); the AF2
    target chain is usually renumbered from 1, so map via ``crop_start``
    (af2_resnum = orig − crop_start + 1). Hotspots that don't map to a present
    residue are 'unmapped'; if none map, returns satisfaction ``None`` + a note.
    """
    binder_cbs = [cb for cb in (_cb(r) for r in binder_res) if cb is not None]
    binder_heavy = _heavy_atoms(binder_res)
    detail: list[dict[str, Any]] = []
    notes: list[str] = []
    n_satisfied = 0
    n_mapped = 0
    for hs in hotspots:
        orig = _parse_hotspot_resnum(hs)
        if orig is None:
            notes.append(f"unparseable hotspot {hs!r}")
            continue
        mapped = orig - crop_start + 1 if crop_start is not None else orig
        res = next((r for r in target_chain if r.id[0] == " " and r.id[1] == mapped), None)
        if res is None:
            detail.append({"hotspot": hs, "mapped_resnum": mapped, "satisfied": None})
            continue
        n_mapped += 1
        hs_cb = _cb(res)
        # Bio.PDB Atom objects do not define truthiness safely (``bool(atom)``
        # delegates to ``len(atom)`` and raises). Test the optional return
        # explicitly so glycine/pseudo-Cbeta handling remains fail-safe.
        min_cb = (
            min((hs_cb - b for b in binder_cbs), default=math.inf)
            if hs_cb is not None
            else math.inf
        )
        hs_heavy = [a for a in res if a.element != "H"]
        min_heavy = min(
            (ha - ba for ha in hs_heavy for ba in binder_heavy), default=math.inf
        )
        sat = min_cb <= _HOTSPOT_CB_CUTOFF or min_heavy <= _HOTSPOT_HEAVY_CUTOFF
        n_satisfied += int(sat)
        detail.append(
            {"hotspot": hs, "mapped_resnum": mapped, "satisfied": bool(sat),
             "min_cb_dist": float(round(min_cb, 2)) if math.isfinite(min_cb) else None}
        )
    if n_mapped == 0:
        notes.append("no hotspots mapped onto the target chain (check crop_start)")
        return {"hotspot_satisfaction": None, "hotspot_detail": detail, "notes": notes}
    return {
        "hotspot_satisfaction": round(n_satisfied / n_mapped, 3),
        "hotspot_detail": detail,
        "notes": notes,
    }


def _parse_hotspot_resnum(hs: str) -> Optional[int]:
    """'A23' / 'A23,' / '23' → 23 (chain letter ignored — we map by number)."""
    digits = "".join(ch for ch in str(hs).strip() if ch.isdigit())
    return int(digits) if digits else None


def parse_cdr_ranges(spec: Any) -> dict[str, list[int]]:
    """Normalise a CDR-range spec to ``{name: [start, end]}`` (1-based inclusive).

    Accepts a dict (``{"cdr1": [27, 38], ...}``), a JSON string of the same, or a
    nanobody ``library.json`` design record (uses its ``cdr1/cdr2/cdr3`` keys).
    Returns ``{}`` for None/unusable input (CDR metrics then degrade to None).
    """
    if not spec:
        return {}
    if isinstance(spec, str):
        import json

        try:
            spec = json.loads(spec)
        except (ValueError, TypeError):
            return {}
    if not isinstance(spec, dict):
        return {}
    out: dict[str, list[int]] = {}
    for name in ("cdr1", "cdr2", "cdr3"):
        rng = spec.get(name)
        if isinstance(rng, (list, tuple)) and len(rng) == 2 and all(isinstance(v, int) for v in rng):
            out[name] = [int(rng[0]), int(rng[1])]
    return out


def _mean_ca_bfactor(chain, resnums: set) -> Optional[float]:
    """Mean Cα B-factor over the given residue numbers (= mean pLDDT for AF2 PDBs)."""
    vals = [
        float(r["CA"].get_bfactor())
        for r in chain
        if r.id[0] == " " and r.id[1] in resnums and "CA" in r
    ]
    return round(sum(vals) / len(vals), 2) if vals else None


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _round_or_none(value: Optional[float], ndigits: int = 3) -> Optional[float]:
    return round(float(value), ndigits) if value is not None and math.isfinite(value) else None


def _ca_residues(chain) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for res in _standard_residues(chain):
        if "CA" not in res:
            continue
        atom = res["CA"]
        out.append(
            {
                "resnum": int(res.id[1]),
                "coord": atom.coord,
                "plddt": float(atom.get_bfactor()),
            }
        )
    return out


def _afm_contact_pairs(binder_ca: list[dict[str, Any]], target_ca: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for b_idx, b in enumerate(binder_ca):
        for t_idx, t in enumerate(target_ca):
            dist = math.dist(b["coord"], t["coord"])
            if dist <= _AFM_CA_CONTACT_CUTOFF:
                pairs.append(
                    {
                        "binder_index": b_idx,
                        "target_index": t_idx,
                        "binder_resnum": b["resnum"],
                        "target_resnum": t["resnum"],
                        "distance": float(dist),
                    }
                )
    return pairs


def _load_afm_scores_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pae = data.get("pae") or data.get("predicted_aligned_error")
    if not isinstance(pae, list):
        raise InterfaceMetricsError(f"AF-M score JSON lacks pae matrix: {path}")
    return {
        "pae": pae,
        "ptm": data.get("ptm"),
        "iptm": data.get("iptm"),
        "max_pae": data.get("max_pae"),
    }


def _find_afm_scores_json(pdb: Path, output_dir: Path) -> Optional[Path]:
    name = pdb.name
    candidates: list[Path] = []
    for tag in ("_unrelaxed_", "_relaxed_"):
        if tag in name:
            candidates.append(output_dir / name.replace(tag, "_scores_").replace(".pdb", ".json"))
    if "_rank_" in name:
        rank = name.split("_rank_", 1)[1][:3]
        candidates.extend(sorted(output_dir.glob(f"*_scores_rank_{rank}_*.json")))
    candidates.extend(sorted(output_dir.glob(f"{pdb.stem}*.json")))
    seen: set[Path] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if cand.exists():
            return cand
    return None


def _rank_number(path: Path) -> int:
    marker = "_rank_"
    if marker not in path.name:
        return 999
    suffix = path.name.split(marker, 1)[1]
    digits = "".join(ch for ch in suffix[:3] if ch.isdigit())
    return int(digits) if digits else 999


def _afm_job_prefix(path: Path) -> Optional[str]:
    for marker in ("_unrelaxed_rank_", "_relaxed_rank_"):
        if marker in path.name:
            return path.name.split(marker, 1)[0]
    return None


def _pdockq(avg_interface_plddt: Optional[float], n_contacts: int) -> Optional[float]:
    if avg_interface_plddt is None or n_contacts <= 0:
        return None
    x = avg_interface_plddt * math.log10(n_contacts)
    return (0.724 / (1 + math.exp(-0.052 * (x - 152.611)))) + 0.018


def _norm_plddt(value: Optional[float]) -> Optional[float]:
    return None if value is None else max(0.0, min(1.0, value / 100.0))


def _norm_pae(value: Optional[float]) -> Optional[float]:
    return None if value is None else max(0.0, min(1.0, (-value / 31.75) + 1.0))


def _combo_feature(best: dict[str, Any], avg: dict[str, Any]) -> Optional[float]:
    factors = [
        best.get("ptm"),
        avg.get("ptm"),
        _norm_plddt(best.get("avg_interface_plddt")),
        _norm_plddt(avg.get("avg_interface_plddt")),
        _norm_pae(best.get("avg_interface_pae")),
        _norm_pae(avg.get("avg_interface_pae")),
    ]
    if any(v is None for v in factors):
        return None
    product = 1.0
    for value in factors:
        product *= float(value)
    return product


def _score_afm_model(
    pdb_path: Path,
    scores_path: Path,
    *,
    binder_chain: str,
    target_chain: str,
) -> dict[str, Any]:
    model = _load_two_chains(str(pdb_path), binder_chain, target_chain)
    binder_ca = _ca_residues(model[binder_chain])
    target_ca = _ca_residues(model[target_chain])
    contacts = _afm_contact_pairs(binder_ca, target_ca)
    scores = _load_afm_scores_json(scores_path)
    pae = scores["pae"]
    n_binder = len(binder_ca)

    pae_values: list[float] = []
    iface_binder: set[int] = set()
    iface_target: set[int] = set()
    unique_pairs: set[tuple[int, int]] = set()
    for pair in contacts:
        bi = pair["binder_index"]
        ti = pair["target_index"]
        # ColabFold concatenates chain A then chain B in the PAE matrix.
        forward = float(pae[bi][n_binder + ti])
        reverse = float(pae[n_binder + ti][bi])
        pae_values.extend([forward, reverse])
        iface_binder.add(pair["binder_resnum"])
        iface_target.add(pair["target_resnum"])
        unique_pairs.add((pair["binder_resnum"], pair["target_resnum"]))

    interface_plddt_values = [
        r["plddt"] for r in binder_ca if r["resnum"] in iface_binder
    ] + [
        r["plddt"] for r in target_ca if r["resnum"] in iface_target
    ]
    avg_interface_plddt = _mean(interface_plddt_values)
    ptm = float(scores["ptm"]) if scores.get("ptm") is not None else None
    iptm = float(scores["iptm"]) if scores.get("iptm") is not None else None
    rtm = None if ptm is None or iptm is None else (0.2 * ptm) + (0.8 * iptm)

    return {
        "pdb_path": str(pdb_path),
        "scores_json_path": str(scores_path),
        "rank": _rank_number(pdb_path),
        "n_contacts": len(contacts),
        "n_interface_residues_binder": len(iface_binder),
        "n_interface_residues_target": len(iface_target),
        "avg_interface_pae": _round_or_none(_mean(pae_values)),
        "avg_interface_plddt": _round_or_none(avg_interface_plddt, 2),
        "ptm": _round_or_none(ptm),
        "iptm": _round_or_none(iptm),
        "rtm": _round_or_none(rtm),
        "pdockq": _round_or_none(_pdockq(avg_interface_plddt, len(contacts))),
        "contact_pairs": sorted(unique_pairs),
    }


def compute_afm_screen_score(
    output_dir: str,
    *,
    complex_pdb_path: Optional[str] = None,
    binder_chain: str = "A",
    target_chain: str = "B",
    max_models: int = 5,
) -> dict[str, Any]:
    """Score a ColabFold/AF-Multimer candidate directory across model variants.

    Mirrors the MRGPRX2 AF-M screen pattern: define interface residue pairs by
    inter-chain Cα distance ≤10 Å, compute interface pLDDT/PAE plus pTM/ipTM,
    calculate pDockQ and a composite ``combo_feature``, and report contact-pair
    support across up to five AF-M model/rank outputs.
    """
    root = Path(output_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise InterfaceMetricsError(f"AF-M output directory not found: {output_dir}")
    pdbs = sorted(
        [p for p in root.glob("*.pdb") if "_rank_" in p.name],
        key=lambda p: (_rank_number(p), p.name),
    )
    job_prefix = None
    if complex_pdb_path:
        job_prefix = _afm_job_prefix(Path(complex_pdb_path))
        if job_prefix is None:
            raise InterfaceMetricsError(
                f"could not infer AF-M job prefix from complex_pdb_path: {complex_pdb_path}"
            )
        pdbs = [p for p in pdbs if _afm_job_prefix(p) == job_prefix]
    if max_models > 0:
        pdbs = pdbs[:max_models]
    if not pdbs:
        suffix = f" for job prefix {job_prefix!r}" if job_prefix else ""
        raise InterfaceMetricsError(f"no ranked AF-M PDBs found in {root}{suffix}")

    model_scores: list[dict[str, Any]] = []
    missing_scores: list[str] = []
    for pdb in pdbs:
        scores = _find_afm_scores_json(pdb, root)
        if scores is None:
            missing_scores.append(str(pdb))
            continue
        model_scores.append(
            _score_afm_model(
                pdb,
                scores,
                binder_chain=binder_chain,
                target_chain=target_chain,
            )
        )
    if not model_scores:
        raise InterfaceMetricsError(
            f"no AF-M model PDBs had matching score JSON files in {root}"
        )

    contact_support: dict[tuple[int, int], int] = {}
    for score in model_scores:
        for pair in score["contact_pairs"]:
            key = tuple(pair)
            contact_support[key] = contact_support.get(key, 0) + 1

    contact_sets = [set(tuple(pair) for pair in score["contact_pairs"]) for score in model_scores]
    pairwise_jaccards: list[float] = []
    for left_index, left in enumerate(contact_sets):
        for right in contact_sets[left_index + 1 :]:
            union = left | right
            # Two models that both predict no interface agree about absence,
            # but that must not look like positive interface reproducibility.
            pairwise_jaccards.append(len(left & right) / len(union) if union else 0.0)
    support_cutoff = max(2, math.ceil(len(model_scores) * 0.6))
    reproducible_contacts = sum(value >= support_cutoff for value in contact_support.values())
    contact_reproducibility = (
        reproducible_contacts / len(contact_support) if contact_support else 0.0
    )

    avg = {
        "n_contacts": _round_or_none(_mean([float(s["n_contacts"]) for s in model_scores]), 2),
        "avg_interface_pae": _round_or_none(_mean([s["avg_interface_pae"] for s in model_scores if s["avg_interface_pae"] is not None])),
        "avg_interface_plddt": _round_or_none(_mean([s["avg_interface_plddt"] for s in model_scores if s["avg_interface_plddt"] is not None]), 2),
        "ptm": _round_or_none(_mean([s["ptm"] for s in model_scores if s["ptm"] is not None])),
        "iptm": _round_or_none(_mean([s["iptm"] for s in model_scores if s["iptm"] is not None])),
        "rtm": _round_or_none(_mean([s["rtm"] for s in model_scores if s["rtm"] is not None])),
        "pdockq": _round_or_none(_mean([s["pdockq"] for s in model_scores if s["pdockq"] is not None])),
    }
    best = sorted(model_scores, key=lambda s: (s["rank"], s["pdb_path"]))[0]
    avg_support = _mean([float(v) for v in contact_support.values()])
    combo = _combo_feature(best, avg)
    iptm_values = [float(s["iptm"]) for s in model_scores if s["iptm"] is not None]
    interface_pae_values = [
        float(s["avg_interface_pae"])
        for s in model_scores
        if s["avg_interface_pae"] is not None
    ]

    public_model_scores = []
    for score in model_scores:
        row = dict(score)
        row.pop("contact_pairs", None)
        public_model_scores.append(row)

    return {
        "output_dir": str(root),
        "job_prefix": job_prefix,
        "num_models_scored": len(model_scores),
        "num_ranked_pdbs_seen": len(pdbs),
        "missing_score_json_pdbs": missing_scores,
        "best_model_rank": best["rank"],
        "best_model": {k: v for k, v in best.items() if k != "contact_pairs"},
        "avg_metrics": avg,
        "n_unique_contacts": len(contact_support),
        "avg_model_support": _round_or_none(avg_support, 2),
        "contact_support_cutoff": support_cutoff,
        "n_reproducible_contacts": reproducible_contacts,
        "contact_reproducibility": _round_or_none(contact_reproducibility),
        "mean_pairwise_contact_jaccard": _round_or_none(_mean(pairwise_jaccards)),
        "iptm_stddev": _round_or_none(statistics.pstdev(iptm_values) if len(iptm_values) > 1 else 0.0),
        "interface_pae_stddev": _round_or_none(
            statistics.pstdev(interface_pae_values) if len(interface_pae_values) > 1 else 0.0
        ),
        "combo_feature": _round_or_none(combo, 6),
        "model_scores": public_model_scores,
        "notes": [
            "Interface contacts use inter-chain CA-CA distance <= 10 A.",
            "combo_feature follows the MRGPRX2 AF-M screen-style pTM/pLDDT/PAE composite.",
            "Final GPCR promotion requires five models and separation from a same-target negative control.",
        ],
    }


def _cdr_metrics(binder_chain, iface_binder: set, cdr_ranges: dict[str, list[int]]) -> dict[str, Any]:
    """Nanobody CDR-aware metrics: interface pLDDT, CDR-H3 pLDDT, CDR-contact fraction.

    ``binder_chain`` is chain A (the nanobody, renumbered from 1 by AF2 so its
    residue numbers == nanobody sequence positions == the ranges in library.json).
    ``cdr_contact_fraction`` = binder interface residues lying in any CDR ÷ total
    binder interface residues — guards against framework-mediated (non-paratope)
    interfaces. ``h3_plddt`` uses the ``cdr3`` range (CDR-H3).
    """
    cdr_positions: set = set()
    for rng in cdr_ranges.values():
        cdr_positions |= set(range(rng[0], rng[1] + 1))
    h3_positions = (
        set(range(cdr_ranges["cdr3"][0], cdr_ranges["cdr3"][1] + 1))
        if "cdr3" in cdr_ranges
        else set()
    )
    interface_plddt = _mean_ca_bfactor(binder_chain, iface_binder)
    h3_plddt = _mean_ca_bfactor(binder_chain, h3_positions)
    if iface_binder and cdr_positions:
        cdr_contact_fraction = round(len(iface_binder & cdr_positions) / len(iface_binder), 3)
    else:
        cdr_contact_fraction = None
    return {
        "interface_plddt": interface_plddt,
        "h3_plddt": h3_plddt,
        "cdr_contact_fraction": cdr_contact_fraction,
    }


def parse_hotspots(spec: Any) -> list[str]:
    """Normalise a hotspot spec ('A23,A107' or ['A23','A107']) to a list."""
    if not spec:
        return []
    if isinstance(spec, str):
        return [h.strip() for h in spec.split(",") if h.strip()]
    if isinstance(spec, (list, tuple)):
        return [str(h).strip() for h in spec if str(h).strip()]
    return []


def compute_interface_metrics(
    complex_pdb: str,
    *,
    binder_chain: str = "A",
    target_chain: str = "B",
    hotspots: Any = None,
    crop_start: Optional[int] = None,
    cdr_ranges: Any = None,
) -> dict[str, Any]:
    """Compute deterministic interface metrics for a binder+target complex PDB.

    Returns a dict with: ``interface_contacts``, ``interface_residues_binder/target``,
    ``interface_bsa`` (Å²), ``clash_score`` (per 1000 atoms) + ``n_clashes``,
    ``contact_geometry``, ``hotspot_satisfaction`` (0–1 or None) + ``hotspot_detail``,
    and ``notes``. Raises ``InterfaceMetricsError`` only for missing file/chain;
    individual metric failures degrade to ``None`` (caller never needs try/except
    per-metric, but should guard the whole call).
    """
    model = _load_two_chains(complex_pdb, binder_chain, target_chain)
    binder_res = _standard_residues(model[binder_chain])
    target_res = _standard_residues(model[target_chain])
    notes: list[str] = []

    contacts = _interface_contacts(binder_res, target_res)
    bsa = _interface_bsa(model, binder_chain, target_chain)
    clash = _clash_score(model, binder_chain, target_chain)
    geom = _contact_geometry(binder_res, target_res, contacts["iface_binder"], contacts["iface_target"])

    hs = parse_hotspots(hotspots)
    if hs:
        hs_result = _hotspot_satisfaction(binder_res, model[target_chain], hs, crop_start)
        notes += hs_result.pop("notes", [])
    else:
        hs_result = {"hotspot_satisfaction": None, "hotspot_detail": []}

    # Nanobody CDR-aware metrics (None for mini-binders / when no CDR ranges given).
    cdrs = parse_cdr_ranges(cdr_ranges)
    cdr_result = (
        _cdr_metrics(model[binder_chain], contacts["iface_binder"], cdrs)
        if cdrs
        else {"interface_plddt": None, "h3_plddt": None, "cdr_contact_fraction": None}
    )

    return {
        "interface_contacts": contacts["n_contacts"],
        "interface_residues_binder": len(contacts["iface_binder"]),
        "interface_residues_target": len(contacts["iface_target"]),
        "interface_residue_ids_binder": sorted(contacts["iface_binder"]),
        "interface_residue_ids_target": sorted(contacts["iface_target"]),
        "interface_bsa": bsa,
        "clash_score": clash["clash_score"],
        "n_clashes": clash["n_clashes"],
        "contact_geometry": geom,
        "hotspot_satisfaction": hs_result["hotspot_satisfaction"],
        "hotspot_detail": hs_result["hotspot_detail"],
        "interface_plddt": cdr_result["interface_plddt"],
        "h3_plddt": cdr_result["h3_plddt"],
        "cdr_contact_fraction": cdr_result["cdr_contact_fraction"],
        "notes": notes,
    }


__all__ = [
    "compute_afm_screen_score",
    "compute_interface_metrics",
    "parse_hotspots",
    "parse_cdr_ranges",
    "InterfaceMetricsError",
]

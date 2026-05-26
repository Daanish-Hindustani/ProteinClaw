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
import math
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
    from Bio.PDB import PDBParser

    path = Path(complex_pdb)
    if not path.exists():
        raise InterfaceMetricsError(f"complex PDB not found: {complex_pdb}")
    model = PDBParser(QUIET=True).get_structure("cx", str(path))[0]
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
        min_cb = min((hs_cb - b for b in binder_cbs), default=math.inf) if hs_cb else math.inf
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

    return {
        "interface_contacts": contacts["n_contacts"],
        "interface_residues_binder": len(contacts["iface_binder"]),
        "interface_residues_target": len(contacts["iface_target"]),
        "interface_bsa": bsa,
        "clash_score": clash["clash_score"],
        "n_clashes": clash["n_clashes"],
        "contact_geometry": geom,
        "hotspot_satisfaction": hs_result["hotspot_satisfaction"],
        "hotspot_detail": hs_result["hotspot_detail"],
        "notes": notes,
    }


__all__ = ["compute_interface_metrics", "parse_hotspots", "InterfaceMetricsError"]

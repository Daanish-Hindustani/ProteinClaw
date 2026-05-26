"""Pure metric extractors.

Each extractor pulls one numeric metric out of a sub-agent's branch payload.
Pure functions: deterministic, side-effect-free, fixture-testable. Phase 6
will swap stub implementations (RMSD, clash, SASA — currently passthroughs)
for real PDB-parsing computations behind the same signature.

The dispatch dict `EXTRACTORS` is the public surface. The Evaluator uses
it to compute every requested metric for a branch, recording None for
metrics absent from the payload.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from pathlib import Path
from typing import Any

from proteinclaw.common.types import Metric

MetricExtractor = Callable[[dict[str, Any]], float | None]
"""Signature shared by every concrete extractor."""


def extract_plddt(payload: dict[str, Any]) -> float | None:
    """Pull pLDDT from a `fold` sub-payload.

    Looks for `payload["fold"]["plddt"]` (the shape produced by the
    `alphafold` tool). Returns None if absent.
    """
    fold = payload.get("fold")
    if not isinstance(fold, dict):
        return None
    value = fold.get("plddt")
    return float(value) if isinstance(value, (int, float)) else None


def extract_ptm(payload: dict[str, Any]) -> float | None:
    """Pull pTM from a `fold` sub-payload."""
    fold = payload.get("fold")
    if not isinstance(fold, dict):
        return None
    value = fold.get("ptm")
    return float(value) if isinstance(value, (int, float)) else None


def extract_binder_monomer_confidence(payload: dict[str, Any]) -> float | None:
    """Use the folded binder's pLDDT as binder monomer confidence."""
    override = _metric_override(payload, "binder_monomer_confidence")
    return override if override is not None else extract_plddt(payload)


def extract_complex_confidence(payload: dict[str, Any]) -> float | None:
    """Extract confidence for the RFdiffusion target+binder complex."""
    override = _metric_override(payload, "complex_confidence")
    if override is not None:
        return override
    designs = _designs(payload)
    if not designs:
        return None
    best = max(
        designs,
        key=lambda d: float(d.get("plddt_estimate", 0.0))
        if isinstance(d.get("plddt_estimate"), (int, float))
        else 0.0,
    )
    value = best.get("plddt_estimate")
    return float(value) if isinstance(value, (int, float)) else None


def extract_novelty(payload: dict[str, Any]) -> float | None:
    """Compute novelty from Foldseek hits (1 - top TM-score).

    Looks for `payload["foldseek"]["hits"]`, a list of dicts with `tm_score`.
    No hits → fully novel (returns 1.0). The list is assumed sorted
    descending by `tm_score` (the Foldseek tool guarantees that), so the
    first element is the closest match.
    """
    fs = payload.get("foldseek")
    if not isinstance(fs, dict):
        return None
    hits = fs.get("hits")
    if not isinstance(hits, list):
        return None
    if not hits:
        return 1.0
    top = hits[0]
    if not isinstance(top, dict):
        return None
    tm = top.get("tm_score")
    if not isinstance(tm, (int, float)):
        return None
    return max(0.0, 1.0 - float(tm))


def extract_passthrough(key: str) -> MetricExtractor:
    """Return an extractor that reads `payload["metrics"][key]` if present.

    Used as a stub for metrics whose real implementation lands in Phase 6
    (RMSD, clash, SASA, constraint satisfaction). Sub-agents that already
    computed the value can stash it in `payload["metrics"]` so the evaluator
    can pick it up without redoing the work.
    """

    def _read(payload: dict[str, Any]) -> float | None:
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            return None
        value = metrics.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    _read.__name__ = f"extract_passthrough_{key}"
    _read.__doc__ = f"Pull payload['metrics'][{key!r}] if present, else None."
    return _read


def extract_interface_contacts(payload: dict[str, Any]) -> float | None:
    """Count target/binder residue-residue contacts in the RFdiffusion complex."""
    override = _metric_override(payload, "interface_contacts")
    if override is not None:
        return override
    analysis = _complex_analysis(payload)
    return float(analysis.interface_contacts) if analysis is not None else None


def extract_interface_sasa(payload: dict[str, Any]) -> float | None:
    """Approximate buried interface SASA from the RFdiffusion complex PDB."""
    override = _metric_override(payload, "interface_sasa")
    if override is not None:
        return override
    analysis = _complex_analysis(payload)
    return analysis.interface_sasa if analysis is not None else None


def extract_clash_score(payload: dict[str, Any]) -> float | None:
    """Compute inter-chain clash count normalized per 1000 binder atoms."""
    override = _metric_override(payload, "clash_score")
    if override is not None:
        return override
    analysis = _complex_analysis(payload)
    return analysis.clash_score if analysis is not None else None


def extract_target_binder_min_distance(payload: dict[str, Any]) -> float | None:
    """Return the closest heavy-atom distance between target and binder."""
    override = _metric_override(payload, "target_binder_min_distance")
    if override is not None:
        return override
    analysis = _complex_analysis(payload)
    return analysis.min_distance if analysis is not None else None


def extract_hotspot_satisfaction(payload: dict[str, Any]) -> float | None:
    """Fraction of requested hotspots contacted by the binder."""
    override = _metric_override(payload, "hotspot_satisfaction")
    if override is not None:
        return override
    hotspots = _hotspot_residues(payload)
    if not hotspots:
        return None
    analysis = _complex_analysis(payload, hotspots=tuple(hotspots))
    return analysis.hotspot_satisfaction if analysis is not None else None


EXTRACTORS: dict[Metric, MetricExtractor] = {
    Metric.PLDDT: extract_plddt,
    Metric.PTM: extract_ptm,
    Metric.NOVELTY: extract_novelty,
    Metric.RMSD: extract_passthrough("rmsd"),
    Metric.CLASH_SCORE: extract_clash_score,
    Metric.INTERFACE_CONTACTS: extract_interface_contacts,
    Metric.INTERFACE_SASA: extract_interface_sasa,
    Metric.TARGET_BINDER_MIN_DISTANCE: extract_target_binder_min_distance,
    Metric.HOTSPOT_SATISFACTION: extract_hotspot_satisfaction,
    Metric.BINDER_MONOMER_CONFIDENCE: extract_binder_monomer_confidence,
    Metric.COMPLEX_CONFIDENCE: extract_complex_confidence,
    Metric.CONSTRAINT_SATISFACTION: extract_passthrough("constraint_satisfaction"),
}
"""Default extractor registry. Phase 6 may override entries with real implementations."""


def compute(metric: Metric, payload: dict[str, Any]) -> float | None:
    """Dispatch to the extractor registered for `metric`.

    Args:
        metric: Which metric to compute.
        payload: Branch payload to read from.

    Returns:
        The extracted value, or None if the metric is not present.
    """
    return EXTRACTORS[metric](payload)


@dataclass(frozen=True)
class _Atom:
    chain: str
    resseq: int
    atom_name: str
    element: str
    x: float
    y: float
    z: float

    @property
    def residue_id(self) -> tuple[str, int]:
        """Chain/residue identifier."""
        return (self.chain, self.resseq)


@dataclass(frozen=True)
class _ComplexAnalysis:
    interface_contacts: int
    interface_sasa: float
    clash_score: float
    min_distance: float
    hotspot_satisfaction: float | None = None


_VDW_RADII = {
    "H": 1.20,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "S": 1.80,
    "P": 1.80,
}
_PROBE_RADIUS = 1.40
_CONTACT_CUTOFF = 5.0
_CLASH_CUTOFF = 2.0
_SASA_POINTS = (
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
    (0.577350269, 0.577350269, 0.577350269),
    (0.577350269, 0.577350269, -0.577350269),
    (0.577350269, -0.577350269, 0.577350269),
    (-0.577350269, 0.577350269, 0.577350269),
)


def _metric_override(payload: dict[str, Any], key: str) -> float | None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _designs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rfd = payload.get("rfdiffusion3")
    if not isinstance(rfd, dict):
        return []
    designs = rfd.get("designs")
    if not isinstance(designs, list):
        return []
    return [d for d in designs if isinstance(d, dict)]


def _best_complex_pdb_path(payload: dict[str, Any]) -> str | None:
    designs = _designs(payload)
    if not designs:
        return None
    best = max(
        designs,
        key=lambda d: float(d.get("plddt_estimate", 0.0))
        if isinstance(d.get("plddt_estimate"), (int, float))
        else 0.0,
    )
    path = best.get("pdb_path")
    return path if isinstance(path, str) else None


def _hotspot_residues(payload: dict[str, Any]) -> tuple[str, ...]:
    for key in ("hotspot_residues", "hotspots"):
        raw = payload.get(key)
        if isinstance(raw, (list, tuple)):
            return tuple(str(x) for x in raw)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        raw = metrics.get("hotspot_residues")
        if isinstance(raw, (list, tuple)):
            return tuple(str(x) for x in raw)
    return ()


def _complex_analysis(
    payload: dict[str, Any], *, hotspots: tuple[str, ...] = ()
) -> _ComplexAnalysis | None:
    path = _best_complex_pdb_path(payload)
    if path is None:
        return None
    try:
        return _analyze_complex(path, hotspots)
    except OSError:
        return None


@lru_cache(maxsize=128)
def _analyze_complex(pdb_path: str, hotspots: tuple[str, ...] = ()) -> _ComplexAnalysis | None:
    atoms = tuple(_parse_heavy_atoms(Path(pdb_path)))
    if not atoms:
        return None
    chains = sorted({a.chain for a in atoms})
    if len(chains) < 2:
        return None
    binder_chain = chains[-1]
    binder = tuple(a for a in atoms if a.chain == binder_chain)
    target = tuple(a for a in atoms if a.chain != binder_chain)
    if not binder or not target:
        return None

    contact_pairs: set[tuple[tuple[str, int], tuple[str, int]]] = set()
    clash_count = 0
    min_dist = float("inf")
    contacted_hotspots: set[str] = set()
    hotspot_ids = {_parse_hotspot(h) for h in hotspots}
    hotspot_ids.discard(None)

    for t in target:
        for b in binder:
            dist = _distance(t, b)
            min_dist = min(min_dist, dist)
            if dist <= _CLASH_CUTOFF:
                clash_count += 1
            if dist <= _CONTACT_CUTOFF:
                contact_pairs.add((t.residue_id, b.residue_id))
                if t.residue_id in hotspot_ids:
                    contacted_hotspots.add(f"{t.chain}{t.resseq}")

    complex_sasa = _sasa(atoms)
    target_sasa = _sasa(target)
    binder_sasa = _sasa(binder)
    buried_sasa = max(0.0, target_sasa + binder_sasa - complex_sasa)
    clash_score = 1000.0 * clash_count / max(1, len(binder))
    hotspot_satisfaction = (
        len(contacted_hotspots) / len(hotspot_ids) if hotspot_ids else None
    )
    return _ComplexAnalysis(
        interface_contacts=len(contact_pairs),
        interface_sasa=buried_sasa,
        clash_score=clash_score,
        min_distance=min_dist,
        hotspot_satisfaction=hotspot_satisfaction,
    )


def _parse_heavy_atoms(path: Path) -> Iterable[_Atom]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        element = (line[76:78].strip() or atom_name[:1]).upper()
        if element == "H" or atom_name.startswith("H"):
            continue
        try:
            chain = line[21:22].strip() or "?"
            resseq = int(line[22:26].strip())
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
        except ValueError:
            continue
        yield _Atom(chain=chain, resseq=resseq, atom_name=atom_name, element=element, x=x, y=y, z=z)


def _parse_hotspot(value: str) -> tuple[str, int] | None:
    chain = value[:1]
    try:
        resseq = int(value[1:])
    except ValueError:
        return None
    if not chain:
        return None
    return (chain, resseq)


def _distance(a: _Atom, b: _Atom) -> float:
    return sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _sasa(atoms: tuple[_Atom, ...]) -> float:
    if not atoms:
        return 0.0
    total = 0.0
    for atom in atoms:
        radius = _VDW_RADII.get(atom.element, 1.70) + _PROBE_RADIUS
        accessible = 0
        for px, py, pz in _SASA_POINTS:
            sx = atom.x + radius * px
            sy = atom.y + radius * py
            sz = atom.z + radius * pz
            if not _is_buried_sample(sx, sy, sz, atom, atoms):
                accessible += 1
        total += 4.0 * 3.141592653589793 * radius * radius * accessible / len(_SASA_POINTS)
    return total


def _is_buried_sample(
    sx: float, sy: float, sz: float, owner: _Atom, atoms: tuple[_Atom, ...]
) -> bool:
    for other in atoms:
        if other is owner:
            continue
        radius = _VDW_RADII.get(other.element, 1.70) + _PROBE_RADIUS
        if (sx - other.x) ** 2 + (sy - other.y) ** 2 + (sz - other.z) ** 2 < radius * radius:
            return True
    return False

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

from collections.abc import Callable
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


EXTRACTORS: dict[Metric, MetricExtractor] = {
    Metric.PLDDT: extract_plddt,
    Metric.PTM: extract_ptm,
    Metric.NOVELTY: extract_novelty,
    Metric.RMSD: extract_passthrough("rmsd"),
    Metric.CLASH_SCORE: extract_passthrough("clash_score"),
    Metric.INTERFACE_SASA: extract_passthrough("interface_sasa"),
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

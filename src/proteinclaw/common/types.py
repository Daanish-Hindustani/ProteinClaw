"""Shared domain enums.

These live in `common/` so orchestrator, evaluator, and tools can reference
them without importing each other (which would violate the strict module
boundary rule). New shared enums go here, never inlined as strings.
"""

from __future__ import annotations

from enum import StrEnum


class Metric(StrEnum):
    """Metrics the Evaluator can produce per branch.

    Every concrete metric implementation in `evaluation/metrics.py` maps to
    exactly one of these values; success criteria reference them by name.
    """

    PLDDT = "plddt"
    PTM = "ptm"
    RMSD = "rmsd"
    CLASH_SCORE = "clash_score"
    INTERFACE_SASA = "interface_sasa"
    NOVELTY = "novelty"
    CONSTRAINT_SATISFACTION = "constraint_satisfaction"


class Comparison(StrEnum):
    """Direction of comparison between an observed metric value and a threshold.

    A SuccessCriterion declares `value <comparison> threshold` (e.g.
    pLDDT >= 0.8 → metric=PLDDT, comparison=GTE, threshold=0.8).
    """

    GTE = "gte"
    LTE = "lte"
    EQ = "eq"


def passes(value: float, threshold: float, comparison: Comparison) -> bool:
    """Evaluate whether `value` satisfies `threshold` under `comparison`.

    Args:
        value: Observed metric value.
        threshold: Target threshold from the SuccessCriterion.
        comparison: How `value` should relate to `threshold`.

    Returns:
        True iff the comparison holds.
    """
    match comparison:
        case Comparison.GTE:
            return value >= threshold
        case Comparison.LTE:
            return value <= threshold
        case Comparison.EQ:
            return value == threshold

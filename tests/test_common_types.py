"""Unit tests for the shared comparison helper."""

from __future__ import annotations

import pytest

from proteinclaw.common.types import Comparison, passes


@pytest.mark.parametrize(
    ("value", "threshold", "comparison", "expected"),
    [
        (0.9, 0.8, Comparison.GTE, True),
        (0.7, 0.8, Comparison.GTE, False),
        (0.8, 0.8, Comparison.GTE, True),
        (0.5, 1.0, Comparison.LTE, True),
        (1.5, 1.0, Comparison.LTE, False),
        (1.0, 1.0, Comparison.EQ, True),
        (1.000001, 1.0, Comparison.EQ, False),
    ],
)
def test_passes_comparisons(
    value: float, threshold: float, comparison: Comparison, expected: bool
) -> None:
    assert passes(value, threshold, comparison) is expected

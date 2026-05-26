from __future__ import annotations

import pytest

from proteinclaw.benchmark.compare import compare_reports, gate_comparison
from proteinclaw.benchmark.models import (
    BenchmarkReport,
    BenchmarkSuite,
    BenchmarkTask,
    BenchmarkTaskResult,
)


def _report(rows: tuple[tuple[str, str, float], ...]) -> BenchmarkReport:
    suite = BenchmarkSuite(
        id="s",
        tasks=tuple(
            BenchmarkTask(id=task_id, prompt=f"prompt for {task_id}")
            for task_id, _, _ in rows
        ),
    )
    return BenchmarkReport.build(
        suite=suite,
        git_branch="b",
        git_commit="c",
        backend_mode="mock",
        task_results=tuple(
            BenchmarkTaskResult(
                task_id=task_id,
                base_task_id=task_id,
                prompt=f"prompt for {task_id}",
                session_id=f"session-{task_id}",
                verdict=verdict,
                metric_scores=({"metric": "plddt", "value": plddt, "passed": True},),
                elapsed_seconds=1.0,
            )
            for task_id, verdict, plddt in rows
        ),
    )


def test_compare_reports_tracks_success_and_metric_deltas() -> None:
    old_rows = (("task_a", "retry", 0.7), ("task_b", "stop_success", 0.8))
    new_rows = (("task_a", "stop_success", 0.9), ("task_b", "stop_success", 0.85))
    old = _report(old_rows)
    new = _report(new_rows)

    comparison = compare_reports(old, new)

    assert comparison.old_success_rate == pytest.approx(0.5)
    assert comparison.new_success_rate == pytest.approx(1.0)
    assert comparison.verdict_count_deltas["stop_success"] == 1

    expected_deltas = {
        task_id: new_plddt - old_plddt
        for (task_id, _, old_plddt), (_, _, new_plddt) in zip(
            old_rows, new_rows, strict=True
        )
    }
    for delta in comparison.task_deltas:
        assert delta.metric_deltas["plddt"] == pytest.approx(expected_deltas[delta.task_id])
    assert comparison.average_metric_deltas["plddt"] == pytest.approx(
        sum(expected_deltas.values()) / len(expected_deltas)
    )


def test_compare_reports_tracks_added_and_missing_tasks() -> None:
    old = _report((("old", "retry", 0.7),))
    new = _report((("new", "retry", 0.7),))

    comparison = compare_reports(old, new)

    assert comparison.missing_in_new == ("old",)
    assert comparison.added_in_new == ("new",)


def test_gate_comparison_passes_improvements() -> None:
    old = _report((("task_a", "retry", 0.7),))
    new = _report((("task_a", "stop_success", 0.8),))

    gate = gate_comparison(compare_reports(old, new))

    assert gate.passed
    assert gate.verdict_regressions == ()


def test_gate_comparison_flags_verdict_regressions() -> None:
    old = _report((("task_a", "stop_success", 0.8),))
    new = _report((("task_a", "retry", 0.7),))

    gate = gate_comparison(compare_reports(old, new))

    assert not gate.passed
    assert gate.verdict_regressions == ("task_a",)
    assert any("verdict regressions" in reason for reason in gate.reasons)


def test_gate_comparison_allows_configured_success_rate_drop() -> None:
    old = _report((("task_a", "stop_success", 0.8), ("task_b", "stop_success", 0.8)))
    new = _report((("task_a", "stop_success", 0.8), ("task_b", "retry", 0.7)))

    gate = gate_comparison(
        compare_reports(old, new),
        min_success_rate_delta=-0.5,
        max_verdict_regressions=1,
    )

    assert gate.passed

"""Comparison helpers for benchmark reports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from proteinclaw.benchmark.models import BenchmarkReport

_VERDICT_RANK = {
    "stop_failure": 0,
    "no_branches": 0,
    "no_tasks": 0,
    "branch": 1,
    "retry": 2,
    "stop_success": 3,
}


@dataclass(frozen=True)
class TaskDelta:
    """Verdict/metric delta for one task shared by two reports."""

    task_id: str
    old_verdict: str
    new_verdict: str
    metric_deltas: dict[str, float]

    @property
    def changed(self) -> bool:
        """True when verdict or at least one metric changed."""
        return self.old_verdict != self.new_verdict or bool(self.metric_deltas)


@dataclass(frozen=True)
class ReportComparison:
    """Structured old/new benchmark comparison."""

    old_success_rate: float
    new_success_rate: float
    verdict_count_deltas: dict[str, int]
    task_deltas: tuple[TaskDelta, ...]
    missing_in_new: tuple[str, ...]
    added_in_new: tuple[str, ...]
    average_metric_deltas: dict[str, float]


@dataclass(frozen=True)
class GateResult:
    """Pass/fail result for benchmark regression gates."""

    passed: bool
    reasons: tuple[str, ...]
    verdict_regressions: tuple[str, ...]
    success_rate_delta: float


def compare_reports(old: BenchmarkReport, new: BenchmarkReport) -> ReportComparison:
    """Compare two benchmark reports by task id."""
    old_by_id = {r.task_id: r for r in old.task_results}
    new_by_id = {r.task_id: r for r in new.task_results}
    shared_ids = sorted(set(old_by_id) & set(new_by_id))

    all_verdicts = set(old.verdict_counts) | set(new.verdict_counts)
    verdict_count_deltas = {
        verdict: new.verdict_counts.get(verdict, 0) - old.verdict_counts.get(verdict, 0)
        for verdict in sorted(all_verdicts)
    }

    task_deltas: list[TaskDelta] = []
    metric_totals: dict[str, list[float]] = defaultdict(list)
    for task_id in shared_ids:
        old_result = old_by_id[task_id]
        new_result = new_by_id[task_id]
        metric_deltas = _metric_deltas(old_result.metric_scores, new_result.metric_scores)
        for metric, delta in metric_deltas.items():
            metric_totals[metric].append(delta)
        task_deltas.append(
            TaskDelta(
                task_id=task_id,
                old_verdict=old_result.verdict,
                new_verdict=new_result.verdict,
                metric_deltas=metric_deltas,
            )
        )

    average_metric_deltas = {
        metric: sum(values) / len(values) for metric, values in sorted(metric_totals.items())
    }
    return ReportComparison(
        old_success_rate=old.success_rate,
        new_success_rate=new.success_rate,
        verdict_count_deltas=verdict_count_deltas,
        task_deltas=tuple(task_deltas),
        missing_in_new=tuple(sorted(set(old_by_id) - set(new_by_id))),
        added_in_new=tuple(sorted(set(new_by_id) - set(old_by_id))),
        average_metric_deltas=average_metric_deltas,
    )


def gate_comparison(
    comparison: ReportComparison,
    *,
    min_success_rate_delta: float = 0.0,
    max_verdict_regressions: int = 0,
) -> GateResult:
    """Evaluate simple old/new regression gates for benchmark reports."""
    success_rate_delta = comparison.new_success_rate - comparison.old_success_rate
    verdict_regressions = tuple(
        delta.task_id
        for delta in comparison.task_deltas
        if _verdict_rank(delta.new_verdict) < _verdict_rank(delta.old_verdict)
    )

    reasons: list[str] = []
    if success_rate_delta < min_success_rate_delta:
        reasons.append(
            "success rate delta "
            f"{success_rate_delta:+.1%} below allowed floor {min_success_rate_delta:+.1%}"
        )
    if len(verdict_regressions) > max_verdict_regressions:
        reasons.append(
            f"{len(verdict_regressions)} verdict regressions exceeds "
            f"allowed maximum {max_verdict_regressions}"
        )
    if comparison.missing_in_new:
        reasons.append(f"missing tasks in new report: {', '.join(comparison.missing_in_new)}")

    return GateResult(
        passed=not reasons,
        reasons=tuple(reasons),
        verdict_regressions=verdict_regressions,
        success_rate_delta=success_rate_delta,
    )


def _metric_deltas(
    old_scores: tuple[dict[str, object], ...], new_scores: tuple[dict[str, object], ...]
) -> dict[str, float]:
    """Return new-old metric deltas for metrics present in both score lists."""
    old_metrics = _metric_values(old_scores)
    new_metrics = _metric_values(new_scores)
    out: dict[str, float] = {}
    for metric in sorted(set(old_metrics) & set(new_metrics)):
        out[metric] = new_metrics[metric] - old_metrics[metric]
    return out


def _metric_values(scores: tuple[dict[str, object], ...]) -> dict[str, float]:
    """Extract numeric metric values from serialized metric score dicts."""
    values: dict[str, float] = {}
    for score in scores:
        metric = score.get("metric")
        value = score.get("value")
        if isinstance(metric, str) and isinstance(value, (int, float)):
            values[metric] = float(value)
    return values


def _verdict_rank(verdict: str) -> int:
    """Return a monotonic quality rank for known benchmark verdicts."""
    return _VERDICT_RANK.get(verdict, 0)

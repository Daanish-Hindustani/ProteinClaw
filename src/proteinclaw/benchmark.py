"""Benchmark panel runner, report builder, and protocol comparison/gate.

Three capabilities:
1. Define a named panel of design tasks (YAML) with optional repeat counts.
2. Build a machine-readable BenchmarkReport (JSON) from the result.json files
   produced by ``run_campaign`` — one entry per task × repeat.
3. Compare two BenchmarkReports (old vs. new protocol) and pass/fail-gate the
   comparison against configurable thresholds.

Hit definition
--------------
A design is a "hit" when:
  af2_complex_plddt > 85  AND  af2_ipsae >= 0.6

These are the two metrics that are always populated once AF2-multimer ran.
Other metrics (iptm, BSA, hotspot satisfaction) are surfaced in the report
but not required for the binary hit call — they are sometimes None depending
on whether ColabFold ran the analysis step.

CLI integration
---------------
The ``proteinclaw benchmark`` sub-app (wired in ``cli.py``) wraps all three
capabilities:
  proteinclaw benchmark run   --panel benchmarks/binder_panel.yaml --output-dir ./benchmarks/runs
  proteinclaw benchmark compare <old_report.json> <new_report.json>
  proteinclaw benchmark gate    <old_report.json> <new_report.json> [--min-hit-rate-delta -0.05]
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import yaml

# ---------------------------------------------------------------------------
# Hit-gate thresholds — aligned with report.py _GATE for the two metrics that
# are *always* populated when AF2-multimer ran.
# ---------------------------------------------------------------------------
HIT_PLDDT_FLOOR = 85.0   # af2_complex_plddt  (strictly greater)
HIT_IPSAE_FLOOR = 0.6    # af2_ipsae           (greater or equal)


# ---------------------------------------------------------------------------
# Panel models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BenchmarkTask:
    """One prompt-level task in a benchmark panel.

    ``repeats`` lets you run the same prompt N times and average the hit rate
    across repeats before gating — one stochastic design run is not enough for
    reliable protocol comparison.
    """

    id: str
    prompt: str
    repeats: int = 1
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkPanel:
    """Ordered list of benchmark tasks loaded from a YAML file."""

    id: str
    description: str
    tasks: tuple[BenchmarkTask, ...]

    @classmethod
    def from_yaml(cls, path: Path) -> "BenchmarkPanel":
        """Load a panel from a YAML file."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tasks = tuple(
            BenchmarkTask(
                id=t["id"],
                prompt=t["prompt"],
                repeats=int(t.get("repeats", 1)),
                tags=tuple(t.get("tags", [])),
            )
            for t in raw.get("tasks", [])
        )
        if not tasks:
            raise ValueError(f"panel {path} contains no tasks")
        return cls(
            id=raw["id"],
            description=raw.get("description", ""),
            tasks=tasks,
        )


# ---------------------------------------------------------------------------
# Per-task result summary (extracted from result.json)
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    """Summary metrics extracted from one task's result.json.

    Keeps only the fields needed for comparison/gate so the benchmark report
    stays small and schema-stable even as result.json grows.
    """

    task_id: str
    repeat: int
    result_json: Path
    total_designs: int
    total_ranked: int
    hit_count: int           # designs clearing the core hit gate
    hit_rate: float          # hit_count / total_ranked; 0.0 when no ranked designs
    best_af2_complex_plddt: Optional[float]
    best_af2_ipsae: Optional[float]
    best_af2_iptm: Optional[float]
    best_interface_bsa: Optional[float]
    best_n_contacts: Optional[int]
    best_clash_score: Optional[float]    # lower is better
    error: Optional[str] = None          # set when result.json is missing/unreadable

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (used by BenchmarkReport.write_json)."""
        d = asdict(self)
        d["result_json"] = str(self.result_json)
        return d


def summarise_result_json(path: Path, *, task_id: str, repeat: int) -> TaskResult:
    """Read a result.json and return a TaskResult summary.

    Never raises — missing or malformed files produce a TaskResult with
    ``error`` set so the benchmark report can surface the failure without
    aborting the entire panel run.
    """
    _empty = dict(
        task_id=task_id,
        repeat=repeat,
        result_json=path,
        total_designs=0,
        total_ranked=0,
        hit_count=0,
        hit_rate=0.0,
        best_af2_complex_plddt=None,
        best_af2_ipsae=None,
        best_af2_iptm=None,
        best_interface_bsa=None,
        best_n_contacts=None,
        best_clash_score=None,
    )
    if not path.exists():
        return TaskResult(**_empty, error="result.json not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return TaskResult(**_empty, error=f"unreadable: {exc}")
    try:
        designs = data.get("designs", [])
        ranked = [d for d in designs if d.get("af2_complex_plddt") is not None]

        def _best(key: str) -> Optional[float]:
            vals = [float(d[key]) for d in ranked if d.get(key) is not None]
            return max(vals) if vals else None

        def _best_lower(key: str) -> Optional[float]:
            vals = [float(d[key]) for d in ranked if d.get(key) is not None]
            return min(vals) if vals else None

        def _best_int(key: str) -> Optional[int]:
            vals = [int(d[key]) for d in ranked if d.get(key) is not None]
            return max(vals) if vals else None

        hits = sum(
            1 for d in ranked
            if (d.get("af2_complex_plddt") or 0.0) > HIT_PLDDT_FLOOR
            and (d.get("af2_ipsae") or 0.0) >= HIT_IPSAE_FLOOR
        )
        total_ranked = len(ranked)
        return TaskResult(
            task_id=task_id,
            repeat=repeat,
            result_json=path,
            total_designs=len(designs),
            total_ranked=total_ranked,
            hit_count=hits,
            hit_rate=hits / total_ranked if total_ranked > 0 else 0.0,
            best_af2_complex_plddt=_best("af2_complex_plddt"),
            best_af2_ipsae=_best("af2_ipsae"),
            best_af2_iptm=_best("af2_iptm"),
            best_interface_bsa=_best("interface_bsa"),
            best_n_contacts=_best_int("n_interface_contacts"),
            best_clash_score=_best_lower("clash_score"),
            error=None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return TaskResult(**_empty, error=f"parse error: {exc}")


# ---------------------------------------------------------------------------
# Benchmark report
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkReport:
    """Aggregated report for one benchmark panel run.

    Written to ``<output_dir>/report.json`` by ``benchmark run``;
    loaded by ``benchmark compare`` and ``benchmark gate``.
    """

    panel_id: str
    panel_description: str
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    task_results: list[TaskResult] = field(default_factory=list)
    # Aggregate fields — set by build(), not the constructor directly.
    overall_hit_rate: float = 0.0
    targets_with_hits: int = 0
    targets_total: int = 0

    @classmethod
    def build(
        cls,
        panel_id: str,
        description: str,
        task_results: list[TaskResult],
    ) -> "BenchmarkReport":
        """Build a report and derive aggregate statistics."""
        total = len(task_results)
        with_hits = sum(1 for r in task_results if r.hit_count > 0)
        all_ranked = sum(r.total_ranked for r in task_results)
        all_hits = sum(r.hit_count for r in task_results)
        overall_hit_rate = all_hits / all_ranked if all_ranked > 0 else 0.0
        return cls(
            panel_id=panel_id,
            panel_description=description,
            task_results=task_results,
            overall_hit_rate=overall_hit_rate,
            targets_with_hits=with_hits,
            targets_total=total,
        )

    def write_json(self, path: Path) -> None:
        """Write the report as pretty JSON, creating parent dirs as needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "panel_id": self.panel_id,
            "panel_description": self.panel_description,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "overall_hit_rate": self.overall_hit_rate,
            "targets_with_hits": self.targets_with_hits,
            "targets_total": self.targets_total,
            "hit_gate": {
                "af2_complex_plddt_gt": HIT_PLDDT_FLOOR,
                "af2_ipsae_gte": HIT_IPSAE_FLOOR,
            },
            "task_results": [r.to_dict() for r in self.task_results],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "BenchmarkReport":
        """Load a previously written report from JSON."""
        data = json.loads(path.read_text(encoding="utf-8"))
        task_results = [
            TaskResult(
                task_id=r["task_id"],
                repeat=r["repeat"],
                result_json=Path(r["result_json"]),
                total_designs=r["total_designs"],
                total_ranked=r["total_ranked"],
                hit_count=r["hit_count"],
                hit_rate=r["hit_rate"],
                best_af2_complex_plddt=r.get("best_af2_complex_plddt"),
                best_af2_ipsae=r.get("best_af2_ipsae"),
                best_af2_iptm=r.get("best_af2_iptm"),
                best_interface_bsa=r.get("best_interface_bsa"),
                best_n_contacts=r.get("best_n_contacts"),
                best_clash_score=r.get("best_clash_score"),
                error=r.get("error"),
            )
            for r in data.get("task_results", [])
        ]
        return cls(
            panel_id=data["panel_id"],
            panel_description=data.get("panel_description", ""),
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            task_results=task_results,
            overall_hit_rate=data["overall_hit_rate"],
            targets_with_hits=data["targets_with_hits"],
            targets_total=data["targets_total"],
        )


# ---------------------------------------------------------------------------
# Comparison and gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskDelta:
    """Per-task hit-rate and metric delta between two reports."""

    task_id: str
    old_hit_rate: float
    new_hit_rate: float
    hit_rate_delta: float
    old_best_plddt: Optional[float]
    new_best_plddt: Optional[float]
    old_best_ipsae: Optional[float]
    new_best_ipsae: Optional[float]

    @property
    def regressed(self) -> bool:
        """True when new hit rate dropped and the old run had at least one hit."""
        return self.hit_rate_delta < 0 and self.old_hit_rate > 0


@dataclass(frozen=True)
class ReportComparison:
    """Structured comparison between an old and a new BenchmarkReport."""

    old_overall_hit_rate: float
    new_overall_hit_rate: float
    hit_rate_delta: float
    old_targets_with_hits: int
    new_targets_with_hits: int
    task_deltas: tuple[TaskDelta, ...]
    missing_in_new: tuple[str, ...]
    added_in_new: tuple[str, ...]


@dataclass(frozen=True)
class GateResult:
    """Pass/fail verdict for a protocol comparison."""

    passed: bool
    reasons: tuple[str, ...]
    regressed_tasks: tuple[str, ...]
    hit_rate_delta: float


def compare_reports(old: BenchmarkReport, new: BenchmarkReport) -> ReportComparison:
    """Compare two BenchmarkReports task-by-task, averaging across repeats."""
    old_by_id: dict[str, list[TaskResult]] = {}
    for r in old.task_results:
        old_by_id.setdefault(r.task_id, []).append(r)

    new_by_id: dict[str, list[TaskResult]] = {}
    for r in new.task_results:
        new_by_id.setdefault(r.task_id, []).append(r)

    shared_ids = sorted(set(old_by_id) & set(new_by_id))
    missing_in_new = tuple(sorted(set(old_by_id) - set(new_by_id)))
    added_in_new = tuple(sorted(set(new_by_id) - set(old_by_id)))

    def _avg_hit_rate(results: list[TaskResult]) -> float:
        rates = [r.hit_rate for r in results]
        return sum(rates) / len(rates) if rates else 0.0

    def _best_plddt(results: list[TaskResult]) -> Optional[float]:
        vals = [r.best_af2_complex_plddt for r in results if r.best_af2_complex_plddt is not None]
        return max(vals) if vals else None

    def _best_ipsae(results: list[TaskResult]) -> Optional[float]:
        vals = [r.best_af2_ipsae for r in results if r.best_af2_ipsae is not None]
        return max(vals) if vals else None

    task_deltas: list[TaskDelta] = []
    for task_id in shared_ids:
        old_hr = _avg_hit_rate(old_by_id[task_id])
        new_hr = _avg_hit_rate(new_by_id[task_id])
        task_deltas.append(TaskDelta(
            task_id=task_id,
            old_hit_rate=old_hr,
            new_hit_rate=new_hr,
            hit_rate_delta=new_hr - old_hr,
            old_best_plddt=_best_plddt(old_by_id[task_id]),
            new_best_plddt=_best_plddt(new_by_id[task_id]),
            old_best_ipsae=_best_ipsae(old_by_id[task_id]),
            new_best_ipsae=_best_ipsae(new_by_id[task_id]),
        ))

    return ReportComparison(
        old_overall_hit_rate=old.overall_hit_rate,
        new_overall_hit_rate=new.overall_hit_rate,
        hit_rate_delta=new.overall_hit_rate - old.overall_hit_rate,
        old_targets_with_hits=old.targets_with_hits,
        new_targets_with_hits=new.targets_with_hits,
        task_deltas=tuple(task_deltas),
        missing_in_new=missing_in_new,
        added_in_new=added_in_new,
    )


def gate_comparison(
    comparison: ReportComparison,
    *,
    min_hit_rate_delta: float = 0.0,
    max_task_regressions: int = 0,
) -> GateResult:
    """Evaluate pass/fail gates on a ReportComparison.

    Args:
        comparison: Output of ``compare_reports``.
        min_hit_rate_delta: The new overall hit rate must be at least this much
            higher (or no lower) than the old one.  Use a negative value to
            tolerate a small drop, e.g. ``-0.05`` for ≤5 pp regression.
        max_task_regressions: Maximum number of individual tasks allowed to
            regress in hit rate.  0 means zero regressions permitted.

    Returns:
        GateResult with ``passed=True`` when all conditions are met.
    """
    regressed = tuple(d.task_id for d in comparison.task_deltas if d.regressed)
    reasons: list[str] = []

    if comparison.hit_rate_delta < min_hit_rate_delta:
        reasons.append(
            f"overall hit-rate delta {comparison.hit_rate_delta:+.1%} "
            f"below allowed floor {min_hit_rate_delta:+.1%}"
        )
    if len(regressed) > max_task_regressions:
        reasons.append(
            f"{len(regressed)} task(s) regressed in hit rate; "
            f"allowed maximum is {max_task_regressions}"
        )
    if comparison.missing_in_new:
        reasons.append(
            f"tasks missing from new report: {', '.join(comparison.missing_in_new)}"
        )

    return GateResult(
        passed=not reasons,
        reasons=tuple(reasons),
        regressed_tasks=regressed,
        hit_rate_delta=comparison.hit_rate_delta,
    )

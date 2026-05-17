"""Benchmark execution for ProteinClaw."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from proteinclaw.benchmark.models import (
    BenchmarkReport,
    BenchmarkSuite,
    BenchmarkTask,
    BenchmarkTaskResult,
)


async def run_suite(config: Any, suite: BenchmarkSuite) -> BenchmarkReport:
    """Run every task in `suite` sequentially and return a report."""
    # Import lazily to keep `proteinclaw.benchmark` independent of
    # `proteinclaw.cli.app`, which imports this module for subcommand wiring.
    from proteinclaw.cli.runner import _build_orchestrator

    orchestrator, _, _ = _build_orchestrator(config)
    results: list[BenchmarkTaskResult] = []
    for task in suite.tasks:
        start = time.perf_counter()
        session = await orchestrator.run(
            task.prompt,
            fanout=task.fanout,
            iterations=task.iterations,
        )
        elapsed = time.perf_counter() - start
        results.append(
            _task_result(
                task=task,
                session_id=session.session_id,
                payload=session.final_payload or {},
                elapsed=elapsed,
            )
        )

    return BenchmarkReport.build(
        suite=suite,
        git_branch=_git_output("rev-parse", "--abbrev-ref", "HEAD"),
        git_commit=_git_output("rev-parse", "HEAD"),
        backend_mode=os.environ.get("PROTEINCLAW_BACKEND", "auto"),
        task_results=tuple(results),
    )


def load_suite(path: Path) -> BenchmarkSuite:
    """Load a benchmark suite file."""
    return BenchmarkSuite.from_yaml(path)


def _task_result(
    *,
    task: BenchmarkTask,
    session_id: str,
    payload: dict[str, Any],
    elapsed: float,
) -> BenchmarkTaskResult:
    """Extract the benchmark result fields from an orchestrator final payload."""
    task_payload = _selected_task_payload(payload)
    return BenchmarkTaskResult(
        task_id=task.id,
        prompt=task.prompt,
        session_id=session_id,
        verdict=str(task_payload.get("verdict") or "no_tasks"),
        winner_branch_id=task_payload.get("winner_branch_id")
        if isinstance(task_payload.get("winner_branch_id"), str)
        else None,
        metric_scores=tuple(
            score for score in task_payload.get("metric_scores", ()) if isinstance(score, dict)
        ),
        elapsed_seconds=elapsed,
        final_task_payload=task_payload,
    )


def _selected_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Pick the first task payload for v1 binder benchmarks."""
    tasks = payload.get("tasks")
    if isinstance(tasks, list) and tasks and isinstance(tasks[0], dict):
        return dict(tasks[0])
    return {}


def _git_output(*args: str) -> str:
    """Return trimmed git command output, or 'unknown' outside git."""
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"

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

_BENCHMARK_SEED_ENV = "PROTEINCLAW_BENCHMARK_SEED"


async def run_suite(config: Any, suite: BenchmarkSuite) -> BenchmarkReport:
    """Run every task in `suite` sequentially and return a report."""
    # Import lazily to keep `proteinclaw.benchmark` independent of
    # `proteinclaw.cli.app`, which imports this module for subcommand wiring.
    from proteinclaw.cli.runner import _build_orchestrator

    orchestrator, _, _ = _build_orchestrator(config)
    results: list[BenchmarkTaskResult] = []
    for task in suite.tasks:
        for repeat_index in range(1, task.repeats + 1):
            seed = _repeat_seed(task, repeat_index)
            start = time.perf_counter()
            with _seed_env(seed):
                session = await orchestrator.run(
                    _prompt_for_repeat(task, repeat_index=repeat_index, seed=seed),
                    fanout=task.fanout,
                    iterations=task.iterations,
                )
            elapsed = time.perf_counter() - start
            results.append(
                _task_result(
                    task=task,
                    repeat_index=repeat_index,
                    seed=seed,
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
    repeat_index: int,
    seed: int | None,
    session_id: str,
    payload: dict[str, Any],
    elapsed: float,
) -> BenchmarkTaskResult:
    """Extract the benchmark result fields from an orchestrator final payload."""
    task_payload = _selected_task_payload(payload)
    return BenchmarkTaskResult(
        task_id=_result_task_id(task, repeat_index),
        base_task_id=task.id,
        repeat_index=repeat_index,
        seed=seed,
        prompt=_prompt_for_repeat(task, repeat_index=repeat_index, seed=seed),
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


def _result_task_id(task: BenchmarkTask, repeat_index: int) -> str:
    """Return the comparable report id for one task repeat."""
    if task.repeats == 1:
        return task.id
    return f"{task.id}__rep{repeat_index:02d}"


def _repeat_seed(task: BenchmarkTask, repeat_index: int) -> int | None:
    """Return a deterministic per-repeat seed when the task defines one."""
    if task.seed is None:
        return None
    return task.seed + repeat_index - 1


def _prompt_for_repeat(task: BenchmarkTask, *, repeat_index: int, seed: int | None) -> str:
    """Append deterministic benchmark metadata for tools/LLMs that honor seeds."""
    if seed is None:
        return task.prompt
    return (
        f"{task.prompt}\n\n"
        f"Benchmark repeat {repeat_index}/{task.repeats}. "
        f"Use deterministic seed {seed} for all stochastic design steps when supported."
    )


class _seed_env:
    """Temporarily expose a benchmark seed to real tool wrappers."""

    def __init__(self, seed: int | None) -> None:
        self._seed = seed
        self._old: str | None = None

    def __enter__(self) -> None:
        if self._seed is None:
            return
        self._old = os.environ.get(_BENCHMARK_SEED_ENV)
        os.environ[_BENCHMARK_SEED_ENV] = str(self._seed)

    def __exit__(self, *exc_info: object) -> None:
        if self._seed is None:
            return
        if self._old is None:
            os.environ.pop(_BENCHMARK_SEED_ENV, None)
        else:
            os.environ[_BENCHMARK_SEED_ENV] = self._old


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

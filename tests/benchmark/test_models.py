from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from proteinclaw.benchmark.models import (
    BenchmarkReport,
    BenchmarkSuite,
    BenchmarkTask,
    BenchmarkTaskResult,
)


def test_suite_loads_from_yaml(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    task_ids = ("target_a", "target_b")
    suite_path.write_text(
        f"""
id: binder_smoke
description: Smoke suite.
tasks:
  - id: {task_ids[0]}
    prompt: Design a binder for PDB 1ABC
    fanout: 1
    iterations: 1
    repeats: 2
    seed: 11
    tags: [binder, mock]
  - id: {task_ids[1]}
    prompt: Design a binder for PDB 2XYZ
    tags: [binder]
""",
        encoding="utf-8",
    )

    suite = BenchmarkSuite.from_yaml(suite_path)

    assert suite.id == "binder_smoke"
    assert tuple(task.id for task in suite.tasks) == task_ids
    assert suite.tasks[0].tags == ("binder", "mock")
    assert suite.tasks[0].repeats == 2
    assert suite.tasks[0].seed == 11
    assert suite.tasks[1].fanout is None
    assert suite.tasks[1].repeats == 1


def test_repo_binder_mock_suite_is_valid() -> None:
    suite_path = (
        Path(__file__).resolve().parents[2] / "config" / "benchmarks" / "binder_mock.yaml"
    )

    suite = BenchmarkSuite.from_yaml(suite_path)

    assert suite.id == "binder_mock"
    assert len(suite.tasks) >= 3
    assert all(task.prompt.startswith("Design a binder") for task in suite.tasks)
    assert len({task.id for task in suite.tasks}) == len(suite.tasks)


def test_repo_binder_real_smoke_suite_is_valid() -> None:
    suite_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "benchmarks"
        / "binder_real_smoke.yaml"
    )

    suite = BenchmarkSuite.from_yaml(suite_path)

    assert suite.id == "binder_real_smoke"
    assert len(suite.tasks) >= 2
    assert all("PDB " in task.prompt for task in suite.tasks)
    assert all("mock" not in task.tags for task in suite.tasks)
    assert len({task.id for task in suite.tasks}) == len(suite.tasks)


def test_repo_binder_real_panel_suite_is_valid() -> None:
    suite_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "benchmarks"
        / "binder_real_panel.yaml"
    )

    suite = BenchmarkSuite.from_yaml(suite_path)
    tags = {tag for task in suite.tasks for tag in task.tags}

    assert suite.id == "binder_real_panel"
    assert len(suite.tasks) >= 5
    assert {"easy", "medium", "hard", "hotspot", "non_hotspot"} <= tags
    assert all(task.repeats >= 2 for task in suite.tasks)
    assert all(task.seed is not None for task in suite.tasks)
    assert len({task.id for task in suite.tasks}) == len(suite.tasks)


def test_suite_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValidationError):
        BenchmarkSuite(
            id="s",
            tasks=(
                BenchmarkTask(id="same", prompt="a"),
                BenchmarkTask(id="same", prompt="b"),
            ),
        )


def test_report_builds_aggregate_fields() -> None:
    verdicts = ("stop_success", "retry", "stop_success")
    suite = BenchmarkSuite(
        id="s",
        tasks=tuple(
            BenchmarkTask(id=f"task_{i}", prompt=f"prompt {i}")
            for i in range(len(verdicts))
        ),
    )
    report = BenchmarkReport.build(
        suite=suite,
        git_branch="branch",
        git_commit="abc",
        backend_mode="mock",
        task_results=(
            tuple(
                BenchmarkTaskResult(
                    task_id=f"task_{i}",
                    base_task_id=f"task_{i}",
                    prompt=f"prompt {i}",
                    session_id=f"session_{i}",
                    verdict=verdict,
                    elapsed_seconds=float(i + 1),
                )
                for i, verdict in enumerate(verdicts)
            )
        ),
    )

    assert report.success_rate == pytest.approx(
        verdicts.count("stop_success") / len(verdicts)
    )
    assert report.verdict_counts == {
        "stop_success": verdicts.count("stop_success"),
        "retry": verdicts.count("retry"),
    }

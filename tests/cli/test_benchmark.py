from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.benchmark.models import (
    BenchmarkReport,
    BenchmarkSuite,
    BenchmarkTask,
    BenchmarkTaskResult,
)
from proteinclaw.cli import app as cli_main
from proteinclaw.cli import config as config_mod


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dir = tmp_path / ".proteinclaw"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", fake_dir / "config.json")


def test_benchmark_run_requires_config(tmp_path: Path) -> None:
    suite = tmp_path / "suite.yaml"
    suite.write_text("id: s\ntasks:\n  - id: t\n    prompt: p\n", encoding="utf-8")

    code = cli_main.main(
        ["benchmark", "run", "--suite", str(suite), "--out", str(tmp_path / "r.json")]
    )

    assert code == 2


def test_benchmark_run_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
id: cli_suite
description: CLI benchmark test suite.
tasks:
  - id: cli_target_1
    prompt: Design a binder for PDB 1ABC
  - id: cli_target_2
    prompt: Design a binder for PDB 2XYZ
""",
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    config_mod.save_config(config_mod.Config(ai_api_key="sk-test"))

    async def fake_run_suite(
        config: config_mod.Config, suite: BenchmarkSuite
    ) -> BenchmarkReport:
        return BenchmarkReport.build(
            suite=suite,
            git_branch="b",
            git_commit="c",
            backend_mode="mock",
            task_results=tuple(
                BenchmarkTaskResult(
                    task_id=task.id,
                    base_task_id=task.id,
                    prompt=task.prompt,
                    session_id=f"session-{task.id}",
                    verdict="stop_success",
                    elapsed_seconds=0.1,
                )
                for task in suite.tasks
            ),
        )

    monkeypatch.setattr(cli_main, "run_suite", fake_run_suite)

    code = cli_main.main(["benchmark", "run", "--suite", str(suite_path), "--out", str(out)])

    assert code == 0
    report = BenchmarkReport.from_json_file(out)
    assert report.suite_id == "cli_suite"
    assert report.success_rate == pytest.approx(1.0)
    assert tuple(result.task_id for result in report.task_results) == (
        "cli_target_1",
        "cli_target_2",
    )


def test_benchmark_compare_reports(tmp_path: Path) -> None:
    suite = BenchmarkSuite(id="s", tasks=(BenchmarkTask(id="t", prompt="p"),))
    old = BenchmarkReport.build(
        suite=suite,
        git_branch="b",
        git_commit="c",
        backend_mode="mock",
        task_results=(
            BenchmarkTaskResult(
                task_id="t",
                base_task_id="t",
                prompt="p",
                session_id="old",
                verdict="retry",
                elapsed_seconds=0.1,
            ),
        ),
    )
    new = BenchmarkReport.build(
        suite=suite,
        git_branch="b",
        git_commit="c",
        backend_mode="mock",
        task_results=(
            BenchmarkTaskResult(
                task_id="t",
                base_task_id="t",
                prompt="p",
                session_id="new",
                verdict="stop_success",
                elapsed_seconds=0.1,
            ),
        ),
    )
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old.write_json(old_path)
    new.write_json(new_path)

    code = cli_main.main(["benchmark", "compare", str(old_path), str(new_path)])

    assert code == 0

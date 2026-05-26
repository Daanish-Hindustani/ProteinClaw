from __future__ import annotations

from typing import Any

import pytest

from proteinclaw.benchmark.models import BenchmarkSuite, BenchmarkTask
from proteinclaw.benchmark.runner import run_suite
from proteinclaw.cli.config import Config


class _Session:
    def __init__(self, session_id: str, final_payload: dict[str, Any]) -> None:
        self.session_id = session_id
        self.final_payload = final_payload


class _Orchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None, int | None]] = []
        self.seeds: list[str | None] = []

    async def run(
        self, prompt: str, *, fanout: int | None = None, iterations: int | None = None
    ) -> _Session:
        import os

        self.calls.append((prompt, fanout, iterations))
        self.seeds.append(os.environ.get("PROTEINCLAW_BENCHMARK_SEED"))
        task_idx = len(self.calls)
        verdict = "stop_success" if task_idx % 2 else "retry"
        plddt = 0.6 + task_idx / 10
        return _Session(
            f"session-{task_idx}",
            {
                "tasks": [
                    {
                        "verdict": verdict,
                        "winner_branch_id": f"branch-{task_idx}",
                        "metric_scores": [
                            {
                                "metric": "plddt",
                                "value": plddt,
                                "passed": verdict == "stop_success",
                            }
                        ],
                        "description": prompt,
                    }
                ]
            },
        )


@pytest.mark.asyncio
async def test_run_suite_uses_orchestrator_and_builds_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _Orchestrator()

    def fake_build_orchestrator(config: Config) -> tuple[_Orchestrator, object, str]:
        assert config.ai_api_key == "sk-test"
        return orchestrator, object(), "/tmp/state"

    monkeypatch.setattr("proteinclaw.cli.runner._build_orchestrator", fake_build_orchestrator)
    tasks = (
        BenchmarkTask(
            id="target_1",
            prompt="Design a binder for PDB 1ABC",
            fanout=1,
            iterations=1,
            repeats=2,
            seed=101,
        ),
        BenchmarkTask(
            id="target_2",
            prompt="Design a binder for PDB 2XYZ",
            fanout=2,
            iterations=1,
        ),
    )
    suite = BenchmarkSuite(
        id="s",
        tasks=tasks,
    )

    report = await run_suite(Config(ai_api_key="sk-test"), suite)

    assert report.suite_id == "s"
    assert report.success_rate == pytest.approx(2 / 3)
    assert len(orchestrator.calls) == 3
    assert orchestrator.calls[0][0].startswith(tasks[0].prompt)
    assert "deterministic seed 101" in orchestrator.calls[0][0]
    assert "deterministic seed 102" in orchestrator.calls[1][0]
    assert orchestrator.calls[2][0] == tasks[1].prompt
    assert orchestrator.seeds == ["101", "102", None]
    assert tuple(call[1:] for call in orchestrator.calls) == (
        (tasks[0].fanout, tasks[0].iterations),
        (tasks[0].fanout, tasks[0].iterations),
        (tasks[1].fanout, tasks[1].iterations),
    )
    assert tuple(result.task_id for result in report.task_results) == (
        "target_1__rep01",
        "target_1__rep02",
        "target_2",
    )
    assert tuple(result.base_task_id for result in report.task_results) == (
        "target_1",
        "target_1",
        "target_2",
    )

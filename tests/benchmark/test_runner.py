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

    async def run(
        self, prompt: str, *, fanout: int | None = None, iterations: int | None = None
    ) -> _Session:
        self.calls.append((prompt, fanout, iterations))
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
    assert report.success_rate == pytest.approx(1 / len(tasks))
    assert tuple(call[0] for call in orchestrator.calls) == tuple(
        task.prompt for task in tasks
    )
    assert tuple(call[1:] for call in orchestrator.calls) == tuple(
        (task.fanout, task.iterations) for task in tasks
    )
    assert tuple(result.task_id for result in report.task_results) == tuple(
        task.id for task in tasks
    )

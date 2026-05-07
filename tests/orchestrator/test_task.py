"""Tests for orchestrator/task.py — immutability, defaults, with_status, round-trip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proteinclaw.common.types import Comparison, Metric
from proteinclaw.orchestrator.task import (
    MAX_ITERATIONS_DEFAULT,
    SuccessCriterion,
    Task,
    TaskResult,
    TaskStatus,
)


def _criterion() -> SuccessCriterion:
    return SuccessCriterion(
        name="confident_fold",
        metric=Metric.PLDDT,
        threshold=0.8,
        comparison=Comparison.GTE,
    )


def test_task_defaults() -> None:
    t = Task(session_id="s1", description="design a binder")
    assert t.task_id  # auto-generated
    assert t.status == TaskStatus.PENDING
    assert t.max_iterations == MAX_ITERATIONS_DEFAULT == 3
    assert t.success_criteria == ()


def test_task_is_frozen() -> None:
    t = Task(session_id="s1", description="x")
    with pytest.raises(ValidationError):
        t.status = TaskStatus.IN_PROGRESS  # type: ignore[misc]


def test_task_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        Task(session_id="s1", description="x", bogus="field")  # type: ignore[call-arg]


def test_task_with_status_returns_new_instance() -> None:
    t = Task(session_id="s1", description="x")
    t2 = t.with_status(TaskStatus.IN_PROGRESS)
    assert t.status == TaskStatus.PENDING  # original untouched
    assert t2.status == TaskStatus.IN_PROGRESS
    assert t.task_id == t2.task_id


def test_task_round_trip_json() -> None:
    t = Task(
        session_id="s1",
        description="design a binder",
        success_criteria=(_criterion(),),
    )
    raw = t.model_dump_json()
    t2 = Task.model_validate_json(raw)
    assert t2 == t


def test_success_criterion_is_frozen() -> None:
    c = _criterion()
    with pytest.raises(ValidationError):
        c.threshold = 0.9  # type: ignore[misc]


def test_task_result_round_trip() -> None:
    r = TaskResult(
        task_id="t1",
        winning_branch_id="b1",
        iterations_used=2,
        status=TaskStatus.COMPLETED,
        payload={"design_count": 4},
    )
    assert TaskResult.model_validate_json(r.model_dump_json()) == r


def test_task_result_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        TaskResult(  # type: ignore[call-arg]
            task_id="t1",
            winning_branch_id=None,
            iterations_used=0,
            status=TaskStatus.FAILED,
            unknown=True,
        )

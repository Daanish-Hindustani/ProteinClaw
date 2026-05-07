"""Task: the unit of work the orchestrator dispatches to the branching service.

A Task is immutable. State changes (status transitions, etc.) produce new
instances via `with_*` helpers — never mutation. This is a deliberate
constraint that enables safe replay from the Trace Store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.types import Comparison, Metric

MAX_ITERATIONS_DEFAULT = 3
"""Default cap on orchestrator iterations per task (PROJECT.md §6 + PLAN.md §4.1)."""


class TaskStatus(StrEnum):
    """Lifecycle of a Task as it flows through the orchestrator loop."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class SuccessCriterion(BaseModel):
    """One declarative success condition on a Task.

    A criterion says "this metric, compared to this threshold, must hold."
    The Evaluator collects observed values per branch and reports which
    criteria pass; the Verdict aggregates those results.

    Attributes:
        name: Human-readable label, surfaced in critiques.
        metric: Which metric carries the relevant signal.
        threshold: Numeric threshold for the comparison.
        comparison: How the observed value must relate to the threshold.
        description: Optional rationale; helps the LLM editor (Phase 7) write
            better critiques.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    metric: Metric
    threshold: float
    comparison: Comparison
    description: str = ""


class Task(BaseModel):
    """One decomposed unit of work produced by the planner.

    Tasks are dispatched to the branching service one at a time. Each task
    flows through up to `max_iterations` rounds of (branch, evaluate,
    refine) before the orchestrator forces a stop.

    Attributes:
        task_id: Unique id; UUIDv4 by default.
        session_id: Owning session (joins traces, evaluations, results).
        description: Natural-language description of the task.
        inputs: Free-form structured inputs (target PDB, hotspot residues, ...).
        success_criteria: Declarative gates the evaluator checks against.
        max_iterations: Upper bound on orchestrator iterations for this task.
        status: Current lifecycle status.
        created_at: UTC creation time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    description: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    success_criteria: tuple[SuccessCriterion, ...] = ()
    max_iterations: int = MAX_ITERATIONS_DEFAULT
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def with_status(self, status: TaskStatus) -> Task:
        """Return a copy with the given status; original is untouched."""
        return self.model_copy(update={"status": status})


class TaskResult(BaseModel):
    """Final outcome of a Task after the iteration loop terminates.

    Attributes:
        task_id: The task this result belongs to.
        winning_branch_id: Branch the orchestrator selected as the result, or
            None if no branch satisfied criteria and the task failed.
        iterations_used: How many iterations the loop consumed (≤ max_iterations).
        status: Terminal status — COMPLETED, FAILED, or ABANDONED.
        payload: Structured result data (file references, predictions, ...).
        finished_at: UTC completion time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    winning_branch_id: str | None
    iterations_used: int
    status: TaskStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

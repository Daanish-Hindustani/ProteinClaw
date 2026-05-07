"""BranchResult: the output of a single sub-agent branch.

Branches are the unit the Branching Service tracks. Each branch is bound to
a specific skill version (recorded as `skill_version_id`) so that two
versions of the same skill can race on a single task — the raw material
the Evolution Service uses for live-run optimization in Phase 7.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class BranchStatus(StrEnum):
    """Lifecycle of a sub-agent branch."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BACKTRACKED = "backtracked"


class BranchResult(BaseModel):
    """One branch's outcome.

    Carries enough metadata for the orchestrator to compare branches, the
    evaluator to score them, and the trace store to reconstruct the branch
    tree (parent_branch_id forms a tree per task).

    Attributes:
        branch_id: Unique id; UUIDv4 by default.
        parent_branch_id: Parent in the branch tree, or None for root branches.
        session_id: Owning session.
        task_id: The task this branch is exploring.
        skill_version_id: Specific skill version bound to this branch. Optional
            because some branches (e.g. analysis-only) don't run a skill.
        depth: 0 for root branches, 1 for children. Capped at 2 (PLAN.md §4.1).
        status: Current lifecycle status.
        payload: Structured result data (designs, intermediate artifacts).
        error: Failure message when status is FAILED. Required when failed,
            but Pydantic doesn't enforce that conditional — the Branching
            Service does.
        started_at: UTC time the branch started executing.
        finished_at: UTC time the branch terminated; None while RUNNING.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_branch_id: str | None = None
    session_id: str
    task_id: str
    skill_version_id: str | None = None
    depth: int = 0
    status: BranchStatus = BranchStatus.RUNNING
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def with_status(
        self,
        status: BranchStatus,
        *,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> BranchResult:
        """Return a copy transitioning to a terminal status.

        Args:
            status: New status (typically COMPLETED, FAILED, or BACKTRACKED).
            payload: Optional payload to attach on completion.
            error: Optional error message to attach on failure.

        Returns:
            A new immutable BranchResult; the original is untouched.
        """
        update: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now(UTC),
        }
        if payload is not None:
            update["payload"] = payload
        if error is not None:
            update["error"] = error
        return self.model_copy(update=update)

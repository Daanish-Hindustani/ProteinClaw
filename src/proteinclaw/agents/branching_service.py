"""BranchingService: spawns and supervises parallel branches per task.

Hard caps from PLAN.md §4.1, validated by Hermes (PLAN.md §4):

- `MAX_FANOUT = 3`: concurrent siblings.
- `MAX_DEPTH = 2`: parent (0) → child (1) → no grandchildren.
- `MAX_TOTAL_BRANCHES = 12`: per-session safety net.

Phase 4 spawns root branches only — children come once skill execution
needs sub-tasks. The cap on totals is checked here regardless so future
recursive expansion stays inside the budget.
"""

from __future__ import annotations

import asyncio
from typing import Any

from proteinclaw.agents.branch_result import BranchResult, BranchStatus
from proteinclaw.agents.budget import (
    MAX_DEPTH,
    MAX_FANOUT,
    MAX_TOTAL_BRANCHES,
    BranchBudget,
    BranchBudgetExceededError,
)
from proteinclaw.agents.permissions import ToolPermissionSet
from proteinclaw.agents.sub_agent import BranchParams, SubAgent
from proteinclaw.common.logging import EventKind, TraceEvent, get_logger
from proteinclaw.memory.trace_store import TraceStore
from proteinclaw.orchestrator.task import Task

# Re-exports — keep MAX_FANOUT/MAX_DEPTH/MAX_TOTAL_BRANCHES + BranchBudget
# importable from this module for callers that already use those paths.
__all__ = [
    "MAX_DEPTH",
    "MAX_FANOUT",
    "MAX_TOTAL_BRANCHES",
    "BranchBudget",
    "BranchBudgetExceededError",
    "BranchingService",
]

_log = get_logger(__name__)


class BranchingService:
    """Concurrent branch supervisor.

    The orchestrator constructs one per session (or one per process in
    Phase 4 — both work because the service is stateless modulo deps)
    and calls `explore()` per task. Total branch count is tracked
    in-process; it resets between explore calls. The orchestrator owns
    cross-task budget enforcement.
    """

    def __init__(
        self,
        *,
        sub_agent: SubAgent,
        trace_store: TraceStore,
    ) -> None:
        """Bind dependencies. Caps are class-level constants — not configurable."""
        self._sub_agent = sub_agent
        self._trace = trace_store

    async def explore(
        self,
        *,
        task: Task,
        fanout: int = MAX_FANOUT,
        max_depth: int = MAX_DEPTH,
        max_total_branches: int = MAX_TOTAL_BRANCHES,
        permissions: ToolPermissionSet | None = None,
    ) -> tuple[BranchResult, ...]:
        """Spawn `fanout` parallel branches for `task` and return their results.

        Args:
            task: Task to explore.
            fanout: How many siblings at depth 0. Clamped to `MAX_FANOUT`.
            max_depth: Maximum tree depth. Clamped to `MAX_DEPTH`. Phase 4
                does not recurse, so this is reserved for Phase 4+.
            max_total_branches: Per-call cap on total branches spawned.
                Defaults to `MAX_TOTAL_BRANCHES`.
            permissions: Permission set for the root branches. Defaults to
                `ToolPermissionSet.parent()`.

        Returns:
            Results in the order branches were spawned. Failed branches
            keep their FAILED status; the orchestrator decides how to
            react.

        Raises:
            BranchBudgetExceededError: If `fanout > max_total_branches`.
        """
        effective_fanout = min(fanout, MAX_FANOUT, max_total_branches)
        if effective_fanout <= 0:
            raise BranchBudgetExceededError(
                f"requested fanout={fanout} would produce 0 branches under cap {max_total_branches}"
            )
        del max_depth  # reserved for Phase 4+ recursive expansion
        perms = permissions or ToolPermissionSet.parent()

        # Shared budget across this fanout, accounting for the root
        # branches we're about to spawn. Children spawned via the LLM
        # executor's `delegate` action draw from the same budget.
        budget = BranchBudget(cap=max_total_branches)
        for _ in range(effective_fanout):
            budget.reserve()

        params_seq = _diversify_params(effective_fanout)
        await asyncio.gather(*(self._emit_spawn(task, idx) for idx in range(effective_fanout)))
        results = await asyncio.gather(
            *(
                self._sub_agent.run(
                    task=task,
                    params=params_seq[idx],
                    permissions=perms,
                    parent_branch_id=None,
                    depth=0,
                    budget=budget,
                )
                for idx in range(effective_fanout)
            )
        )
        for r in results:
            if r.status is BranchStatus.FAILED:
                _log.info(
                    "branch_failed",
                    branch_id=r.branch_id,
                    task_id=task.task_id,
                    error=r.error,
                )
        return tuple(results)

    async def _emit_spawn(self, task: Task, idx: int) -> None:
        """Record a `BRANCH_SPAWNED` event before the branch starts running."""
        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "fanout_index": idx,
        }
        await self._trace.append(
            TraceEvent(
                session_id=task.session_id,
                component="agent.branching_service",
                kind=EventKind.BRANCH_SPAWNED,
                branch_id=None,
                parent_branch_id=None,
                payload=payload,
            )
        )


def _diversify_params(fanout: int) -> tuple[BranchParams, ...]:
    """Return `fanout` distinct BranchParams so siblings produce different mocks.

    With deterministic mock backends, identical inputs yield identical
    outputs — the diversification ensures the trace tree is meaningful.
    The values themselves are chosen to be plausible across real tools too.
    """
    presets = (
        BranchParams(num_designs=4, num_sequences=4, sampling_temperature=0.1, use_msa=False),
        BranchParams(num_designs=6, num_sequences=4, sampling_temperature=0.2, use_msa=True),
        BranchParams(num_designs=3, num_sequences=8, sampling_temperature=0.3, use_msa=False),
    )
    if fanout > len(presets):  # pragma: no cover — capped to MAX_FANOUT==3 today
        raise ValueError(f"fanout {fanout} exceeds preset count {len(presets)}")
    return presets[:fanout]

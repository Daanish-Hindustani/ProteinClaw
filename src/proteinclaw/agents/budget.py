"""Session-shared branch budget.

Tracks how many branches (root + delegated children) have been spawned
in a session. Lives in its own module to avoid the circular import that
arises when both ``branching_service`` and ``sub_agent`` need it.
"""

from __future__ import annotations

MAX_FANOUT = 3
"""Concurrent siblings per task (per PLAN.md §4.1)."""

MAX_DEPTH = 2
"""Branch tree depth: parent (0) → child (1). No grandchildren."""

MAX_TOTAL_BRANCHES = 12
"""Per-session safety net (per PLAN.md §4.1)."""


class BranchBudgetExceededError(RuntimeError):
    """Raised when a session would exceed `MAX_TOTAL_BRANCHES`."""


class BranchBudget:
    """Tracks how many branches have been spawned in a session.

    Used by parent sub-agents that delegate sub-tasks to children. The
    budget is **shared** across siblings so a parent that spawns 3 root
    branches plus their delegated children can't blow through the
    per-session cap collectively.
    """

    def __init__(self, *, cap: int = MAX_TOTAL_BRANCHES) -> None:
        """Construct a fresh budget capped at `cap`."""
        if cap < 0:
            raise ValueError("cap must be non-negative")
        self._cap = cap
        self._spawned = 0

    @property
    def remaining(self) -> int:
        """Branches still allowed before the cap is hit."""
        return max(0, self._cap - self._spawned)

    def reserve(self) -> None:
        """Reserve one slot. Raises `BranchBudgetExceededError` when full."""
        if self._spawned >= self._cap:
            raise BranchBudgetExceededError(
                f"branch budget exhausted ({self._spawned}/{self._cap})"
            )
        self._spawned += 1

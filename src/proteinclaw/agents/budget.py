"""Session-shared branch budget.

Tracks how many branches (root + delegated children) have been spawned
in a session. Lives in its own module to avoid the circular import that
arises when both ``branching_service`` and ``sub_agent`` need it.
"""

from __future__ import annotations

MAX_FANOUT = 1
"""Concurrent siblings per task.

Lowered from PLAN.md's original 3 to 1: 3 root branches × 3 iterations
multiplied wall-clock by ~9× while delivering little extra information
in early development (each branch spent most of its budget repeating
the same recovery dance). Override per-run via the CLI ``--fanout``
flag when you actually want parallel exploration."""

MAX_DEPTH = 2
"""Branch tree depth: parent (0) → child (1). No grandchildren."""

MAX_TOTAL_BRANCHES = 36
"""Per-session safety net.

Original value was 12 (PLAN.md §4.1) which assumed delegation was rare.
Once delegation actually fires (post-fix #4 in the agent loop), the
budget is consumed by ``fanout × iterations + per-branch delegations``:
3 × 3 = 9 reserved for roots leaves only 3 for children, which the
LLM exhausts on the first iteration. 36 fits 9 roots plus ~3 children
each — comfortable for binder workflows that fan out per-design and
per-sequence."""


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

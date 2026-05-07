"""Sub-agent capability restrictions.

Hermes-validated pattern (see PLAN.md §4.2): children of sub-agents are
denied recursive delegation, memory writes, user clarification, and
cross-channel side effects. They retain Python sandbox + tool access.

The `ToolPermissionSet` rides with each branch's context. Operations that
could violate the contract consult their permissions and raise
`PermissionDeniedError` rather than silently no-op'ing — the failure must
surface in the trace.
"""

from __future__ import annotations

from dataclasses import dataclass


class PermissionDeniedError(RuntimeError):
    """Raised when a branch attempts an operation outside its permissions.

    Carries the violated permission name so the trace event can record it.
    """

    def __init__(self, permission: str, message: str | None = None) -> None:
        """Construct a denial attached to `permission`."""
        super().__init__(message or f"permission denied: {permission}")
        self.permission = permission


@dataclass(frozen=True)
class ToolPermissionSet:
    """Capability flags carried with every branch context.

    Attributes:
        can_delegate: Spawn child sub-agents. False on children to prevent
            unbounded delegation trees.
        can_write_memory: Persist to the Session/Trace stores beyond the
            standard branch-completion event. False on children to avoid
            concurrent state corruption (only the parent serializes writes).
        can_ask_user: Block the run on user clarification. False on
            children — they cannot introduce latency-blocking prompts.
        can_run_sandbox: Run untrusted code via the Python sandbox.
            Always True so far; reserved for future contexts that lock it
            down (e.g. an audit-only branch).
        can_invoke_tools: Call protein-design tools. Always True so far;
            reserved for the same reason.
    """

    can_delegate: bool
    can_write_memory: bool
    can_ask_user: bool
    can_run_sandbox: bool = True
    can_invoke_tools: bool = True

    @classmethod
    def parent(cls) -> ToolPermissionSet:
        """Permissions for a root branch / orchestrator-owned context."""
        return cls(can_delegate=True, can_write_memory=True, can_ask_user=True)

    @classmethod
    def child(cls) -> ToolPermissionSet:
        """Permissions for a child branch (depth ≥ 1)."""
        return cls(can_delegate=False, can_write_memory=False, can_ask_user=False)

    def require(self, permission: str) -> None:
        """Raise `PermissionDeniedError` if `permission` is not granted.

        Args:
            permission: One of the boolean attribute names on this dataclass.

        Raises:
            PermissionDeniedError: When the named permission is False.
            AttributeError: When `permission` is not a known attribute.
        """
        value = getattr(self, permission)
        if not isinstance(value, bool):
            raise AttributeError(f"unknown permission: {permission}")
        if not value:
            raise PermissionDeniedError(permission)

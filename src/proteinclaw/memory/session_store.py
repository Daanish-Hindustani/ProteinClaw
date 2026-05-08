"""Session Store: live run state.

A Session is the top-level container the orchestrator owns for a single
user request. It is immutable; updates produce new instances via `with_*`
helpers. The store itself is mutable — it maps session_id to the latest
Session snapshot.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.memory._sqlite import execute_script, open_connection


class Session(BaseModel):
    """Live state of a single user-facing run.

    The orchestrator constructs a Session at intake, mutates it through the
    8-stage workflow by replacing it via `with_*` helpers, and finalizes it
    once the iteration loop exits.

    Attributes:
        session_id: Unique id; UUIDv4 by default.
        user_request: Original natural-language request, verbatim.
        started_at: UTC creation time.
        ended_at: UTC completion time, or None while running.
        task_ids: Tasks the planner produced for this session.
        active_branch_ids: Branches currently in-flight.
        iterations_used: Total orchestrator iterations consumed so far
            (across all tasks; the per-task cap is on Task.max_iterations).
        final_payload: Aggregated final result, set on completion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_request: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    task_ids: tuple[str, ...] = ()
    active_branch_ids: tuple[str, ...] = ()
    iterations_used: int = 0
    final_payload: dict[str, Any] | None = None

    def with_task(self, task_id: str) -> Session:
        """Return a copy with `task_id` appended to task_ids."""
        return self.model_copy(update={"task_ids": (*self.task_ids, task_id)})

    def with_active_branches(self, branch_ids: tuple[str, ...]) -> Session:
        """Return a copy whose active_branch_ids is replaced with `branch_ids`."""
        return self.model_copy(update={"active_branch_ids": branch_ids})

    def with_iteration_increment(self) -> Session:
        """Return a copy with iterations_used incremented by 1."""
        return self.model_copy(update={"iterations_used": self.iterations_used + 1})

    def finalized(self, payload: dict[str, Any]) -> Session:
        """Return a copy marked complete with `payload` as the final result."""
        return self.model_copy(
            update={
                "final_payload": payload,
                "ended_at": datetime.now(UTC),
                "active_branch_ids": (),
            }
        )


@runtime_checkable
class SessionStore(Protocol):
    """Persistence surface for Session snapshots.

    Implementations are key-value over `session_id`. Phase 5 swaps the
    in-memory map for SQLite without changing this Protocol.
    """

    async def get(self, session_id: str) -> Session | None:
        """Return the latest snapshot for `session_id`, or None if unknown."""
        ...

    async def save(self, session: Session) -> None:
        """Persist `session` as the latest snapshot for its id."""
        ...


class InMemorySessionStore:
    """Process-local session store. Default for tests."""

    def __init__(self) -> None:
        """Initialize an empty session map."""
        self._sessions: dict[str, Session] = {}

    async def get(self, session_id: str) -> Session | None:
        """Return the latest snapshot for `session_id`, or None if unknown."""
        return self._sessions.get(session_id)

    async def save(self, session: Session) -> None:
        """Persist `session` as the latest snapshot for its id."""
        self._sessions[session.session_id] = session


_SESSION_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SQLiteSessionStore:
    """SQLite-backed SessionStore.

    Stores the full Session as a JSON blob keyed by `session_id`. Saves
    overwrite — there's only ever one current snapshot per session.
    """

    def __init__(self, path: Path) -> None:
        """Bind the store to `path`. Schema is created on first connect."""
        self._path = path
        self._lock = asyncio.Lock()
        execute_script(path, _SESSION_DDL)

    async def get(self, session_id: str) -> Session | None:
        """Return the latest snapshot for `session_id`, or None if unknown."""
        return await asyncio.to_thread(self._get_sync, session_id)

    def _get_sync(self, session_id: str) -> Session | None:
        """Synchronous read helper."""
        with open_connection(self._path) as con:
            row = con.execute(
                "SELECT snapshot_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return Session.model_validate_json(row["snapshot_json"])

    async def save(self, session: Session) -> None:
        """Persist `session` as the latest snapshot for its id (UPSERT)."""
        async with self._lock:
            await asyncio.to_thread(self._save_sync, session)

    def _save_sync(self, session: Session) -> None:
        """Synchronous upsert helper."""
        with open_connection(self._path) as con:
            con.execute(
                """INSERT INTO sessions(session_id, snapshot_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       snapshot_json = excluded.snapshot_json,
                       updated_at = excluded.updated_at""",
                (
                    session.session_id,
                    session.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

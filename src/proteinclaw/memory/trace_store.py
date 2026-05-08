"""Trace Store: append-only log of TraceEvents.

Two implementations live here for Phase 1:

- `InMemoryTraceStore`: default for tests and short runs.
- `JsonlTraceStore`: file-backed, useful for local debugging and as a
  portable artifact.

Phase 5 replaces both with a SQLite + FTS5 implementation behind the same
Protocol — no caller changes required.

Replaying events from a TraceStore in `event_id` insertion order MUST be
sufficient to reconstruct the session. This is a correctness requirement,
not a nice-to-have.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from proteinclaw.common.logging import EventKind, TraceEvent
from proteinclaw.memory._sqlite import execute_script, open_connection


@runtime_checkable
class TraceStore(Protocol):
    """Append-only trace event log.

    Implementations MUST:
    - preserve insertion order within a session,
    - never modify events after they are appended,
    - return an empty list for unknown ids (never raise).
    """

    async def append(self, event: TraceEvent) -> None:
        """Persist one event. Order is the order of successful appends."""
        ...

    async def read_session(self, session_id: str) -> list[TraceEvent]:
        """Return all events for a session in insertion order."""
        ...

    async def read_branch(self, branch_id: str) -> list[TraceEvent]:
        """Return all events for a branch in insertion order."""
        ...


class InMemoryTraceStore:
    """Process-local trace store. Default for tests and short runs."""

    def __init__(self) -> None:
        """Initialize an empty event list."""
        self._events: list[TraceEvent] = []
        self._lock = asyncio.Lock()

    async def append(self, event: TraceEvent) -> None:
        """Append an event under a lock so concurrent producers stay ordered."""
        async with self._lock:
            self._events.append(event)

    async def read_session(self, session_id: str) -> list[TraceEvent]:
        """Return events for `session_id` in insertion order."""
        return [e for e in self._events if e.session_id == session_id]

    async def read_branch(self, branch_id: str) -> list[TraceEvent]:
        """Return events for `branch_id` in insertion order."""
        return [e for e in self._events if e.branch_id == branch_id]


class JsonlTraceStore:
    """File-backed trace store writing one JSON event per line.

    Async-safe via an in-process lock. Cross-process safety is not provided
    in Phase 1 — when multiple producers need to share a store, switch to
    the SQLite implementation in Phase 5.
    """

    def __init__(self, path: Path) -> None:
        """Bind the store to `path`. Parent directory must exist."""
        self._path = path
        self._lock = asyncio.Lock()

    async def append(self, event: TraceEvent) -> None:
        """Append a JSONL record. Disk I/O runs in a worker thread."""
        line = event.model_dump_json() + "\n"
        async with self._lock:
            await asyncio.to_thread(self._write_line, line)

    def _write_line(self, line: str) -> None:
        """Synchronous file append helper invoked under the asyncio.to_thread bridge."""
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    async def _read_all(self) -> list[TraceEvent]:
        """Load every event from disk; cheap enough at Phase 1 trace volumes."""
        if not self._path.exists():
            return []
        text = await asyncio.to_thread(self._path.read_text, "utf-8")
        return [TraceEvent.model_validate_json(line) for line in text.splitlines() if line.strip()]

    async def read_session(self, session_id: str) -> list[TraceEvent]:
        """Return events for `session_id` in insertion order."""
        return [e for e in await self._read_all() if e.session_id == session_id]

    async def read_branch(self, branch_id: str) -> list[TraceEvent]:
        """Return events for `branch_id` in insertion order."""
        return [e for e in await self._read_all() if e.branch_id == branch_id]


_TRACE_DDL = """
CREATE TABLE IF NOT EXISTS trace_events (
    insertion_order INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    component TEXT NOT NULL,
    kind TEXT NOT NULL,
    branch_id TEXT,
    parent_branch_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_session
    ON trace_events(session_id, insertion_order);
CREATE INDEX IF NOT EXISTS idx_trace_branch
    ON trace_events(branch_id, insertion_order);

CREATE VIRTUAL TABLE IF NOT EXISTS trace_events_fts USING fts5(
    event_id UNINDEXED,
    session_id,
    component,
    kind,
    payload_text
);
"""


class SQLiteTraceStore:
    """SQLite-backed TraceStore with FTS5 over event payloads.

    Events are append-only — `insertion_order` is the AUTOINCREMENT
    primary key, so reads in `insertion_order` ASC reproduce the exact
    sequence appends happened in (independent of timestamp). The FTS5
    virtual table is updated alongside `trace_events` on every append so
    `search()` is a single SQL call.
    """

    def __init__(self, path: Path) -> None:
        """Bind the store to `path`. Schema is created on first connect."""
        self._path = path
        self._lock = asyncio.Lock()
        execute_script(path, _TRACE_DDL)

    async def append(self, event: TraceEvent) -> None:
        """Insert one event into the trace_events + FTS5 tables atomically."""
        async with self._lock:
            await asyncio.to_thread(self._append_sync, event)

    def _append_sync(self, event: TraceEvent) -> None:
        """Synchronous insert helper invoked under the asyncio.to_thread bridge."""
        payload_json = json.dumps(event.payload, sort_keys=True, default=str)
        with open_connection(self._path) as con:
            con.execute(
                """INSERT INTO trace_events
                   (event_id, timestamp, session_id, component, kind,
                    branch_id, parent_branch_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.timestamp.isoformat(),
                    event.session_id,
                    event.component,
                    event.kind.value,
                    event.branch_id,
                    event.parent_branch_id,
                    payload_json,
                ),
            )
            con.execute(
                """INSERT INTO trace_events_fts
                   (event_id, session_id, component, kind, payload_text)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.session_id,
                    event.component,
                    event.kind.value,
                    payload_json,
                ),
            )

    async def read_session(self, session_id: str) -> list[TraceEvent]:
        """Return events for `session_id` in insertion order."""
        return await asyncio.to_thread(
            self._read_filter,
            "WHERE session_id = ?",
            (session_id,),
        )

    async def read_branch(self, branch_id: str) -> list[TraceEvent]:
        """Return events for `branch_id` in insertion order."""
        return await asyncio.to_thread(
            self._read_filter,
            "WHERE branch_id = ?",
            (branch_id,),
        )

    def _read_filter(self, where: str, params: tuple[Any, ...]) -> list[TraceEvent]:
        """Run a parameterized SELECT and hydrate rows into TraceEvent."""
        with open_connection(self._path) as con:
            rows = con.execute(
                f"""SELECT event_id, timestamp, session_id, component, kind,
                           branch_id, parent_branch_id, payload_json
                    FROM trace_events {where}
                    ORDER BY insertion_order ASC""",
                params,
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TraceEvent]:
        """Run a full-text search (FTS5 MATCH) over event payloads.

        Args:
            query: FTS5 query string (e.g. ``"branch_completed"``).
            session_id: Optional scope to a single session.
            limit: Maximum number of results.

        Returns:
            Matching events. Ordering is FTS5 relevance.
        """
        return await asyncio.to_thread(self._search_sync, query, session_id, limit)

    def _search_sync(self, query: str, session_id: str | None, limit: int) -> list[TraceEvent]:
        """Synchronous FTS5 search helper."""
        sql = """SELECT t.event_id, t.timestamp, t.session_id, t.component, t.kind,
                      t.branch_id, t.parent_branch_id, t.payload_json
               FROM trace_events_fts f
               JOIN trace_events t ON t.event_id = f.event_id
               WHERE trace_events_fts MATCH ?"""
        params: list[Any] = [query]
        if session_id is not None:
            sql += " AND t.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with open_connection(self._path) as con:
            rows = con.execute(sql, params).fetchall()
        return [_row_to_event(r) for r in rows]


def _row_to_event(row: sqlite3.Row) -> TraceEvent:
    """Hydrate a SQLite row into the immutable `TraceEvent` model."""
    return TraceEvent(
        event_id=row["event_id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        session_id=row["session_id"],
        component=row["component"],
        kind=EventKind(row["kind"]),
        branch_id=row["branch_id"],
        parent_branch_id=row["parent_branch_id"],
        payload=json.loads(row["payload_json"]),
    )

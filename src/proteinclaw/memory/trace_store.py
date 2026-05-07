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
from pathlib import Path
from typing import Protocol, runtime_checkable

from proteinclaw.common.logging import TraceEvent


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

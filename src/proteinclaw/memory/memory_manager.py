"""MemoryManager: facade over Knowledge / Session / Trace stores plus compaction.

The orchestrator and sub-agents talk to one MemoryManager; the manager
routes calls to the right store. This keeps callers from having to import
three Protocols and threading them through every layer.

The manager is intentionally thin — it does not own additional state
beyond the bound stores. Phase 7's Evolution Service uses
`compact_session()` to feed Feedback Descent's reflection material.
"""

from __future__ import annotations

from typing import Literal

from proteinclaw.common.logging import TraceEvent
from proteinclaw.memory.compaction import (
    CompactionResult,
    Compactor,
)
from proteinclaw.memory.knowledge_store import (
    Knowledge,
    KnowledgeKind,
    SQLiteKnowledgeStore,
)
from proteinclaw.memory.session_store import Session, SessionStore
from proteinclaw.memory.trace_store import SQLiteTraceStore, TraceStore


class MemoryManager:
    """Unified facade.

    Construct once per session-creating process. The bound stores can be
    in-memory (tests) or SQLite (production) — the manager doesn't care.
    """

    def __init__(
        self,
        *,
        knowledge: SQLiteKnowledgeStore,
        sessions: SessionStore,
        traces: TraceStore,
        compactor: Compactor | None = None,
    ) -> None:
        """Bind dependencies. Compactor defaults to one with the standard threshold."""
        self._knowledge = knowledge
        self._sessions = sessions
        self._traces = traces
        self._compactor = compactor or Compactor()

    # ----- TraceStore facade --------------------------------------------------

    async def record(self, event: TraceEvent) -> None:
        """Append a TraceEvent to the trace store."""
        await self._traces.append(event)

    async def read_session_trace(self, session_id: str) -> list[TraceEvent]:
        """Return events for a session in insertion order."""
        return await self._traces.read_session(session_id)

    async def read_branch_trace(self, branch_id: str) -> list[TraceEvent]:
        """Return events for a branch in insertion order."""
        return await self._traces.read_branch(branch_id)

    # ----- SessionStore facade -----------------------------------------------

    async def get_session(self, session_id: str) -> Session | None:
        """Return the latest session snapshot, or None if unknown."""
        return await self._sessions.get(session_id)

    async def save_session(self, session: Session) -> None:
        """Persist a session snapshot."""
        await self._sessions.save(session)

    # ----- KnowledgeStore facade ---------------------------------------------

    async def add_knowledge(self, item: Knowledge) -> None:
        """Persist a knowledge entry."""
        await self._knowledge.add(item)

    async def get_knowledge(self, knowledge_id: str) -> Knowledge | None:
        """Return a knowledge entry by id, or None."""
        return await self._knowledge.get(knowledge_id)

    async def list_knowledge_by_kind(self, kind: KnowledgeKind) -> list[Knowledge]:
        """Return all knowledge entries of a given kind."""
        return await self._knowledge.list_by_kind(kind)

    # ----- Recall: unified search across stores ------------------------------

    async def recall(
        self,
        query: str,
        *,
        store: Literal["knowledge", "trace"] = "knowledge",
        session_id: str | None = None,
        kind: KnowledgeKind | None = None,
        limit: int = 20,
    ) -> list[Knowledge] | list[TraceEvent]:
        """Search either the knowledge store or the trace store.

        Args:
            query: FTS5 query string.
            store: Which store to search.
            session_id: Trace-store only. Scope to a session when set.
            kind: Knowledge-store only. Filter to a kind when set.
            limit: Maximum results.

        Returns:
            Matching `Knowledge` entries or `TraceEvent`s, depending on
            `store`. The caller already knew which they wanted.
        """
        if store == "knowledge":
            return await self._knowledge.search(query, kind=kind, limit=limit)
        if not isinstance(self._traces, SQLiteTraceStore):
            raise NotImplementedError("Trace recall requires the SQLite TraceStore implementation")
        return await self._traces.search(query, session_id=session_id, limit=limit)

    # ----- Compaction --------------------------------------------------------

    async def compact_session(
        self, session_id: str, *, force: bool = False
    ) -> CompactionResult | None:
        """Compact the trace for `session_id` if it exceeds the threshold.

        Args:
            session_id: Session to compact.
            force: Bypass `should_compact()` and always compact.

        Returns:
            The compaction result, or None when below threshold and not forced.
            A None return is the explicit "nothing to do" signal — callers
            should not infer compaction happened from a missing return.
        """
        events = await self._traces.read_session(session_id)
        if not events:
            return None
        if not force and not self._compactor.should_compact(events):
            return None
        return self._compactor.compact(events)

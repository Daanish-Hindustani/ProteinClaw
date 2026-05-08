"""Tests for MemoryManager — facade routing, recall, compaction integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.common.logging import EventKind, TraceEvent
from proteinclaw.memory.compaction import Compactor
from proteinclaw.memory.knowledge_store import (
    Knowledge,
    KnowledgeKind,
    SQLiteKnowledgeStore,
)
from proteinclaw.memory.memory_manager import MemoryManager
from proteinclaw.memory.session_store import (
    InMemorySessionStore,
    Session,
    SQLiteSessionStore,
)
from proteinclaw.memory.trace_store import (
    InMemoryTraceStore,
    SQLiteTraceStore,
)


def _manager(tmp_path: Path, *, threshold: int = 3) -> MemoryManager:
    return MemoryManager(
        knowledge=SQLiteKnowledgeStore(tmp_path / "k.db"),
        sessions=SQLiteSessionStore(tmp_path / "s.db"),
        traces=SQLiteTraceStore(tmp_path / "t.db"),
        compactor=Compactor(threshold=threshold),
    )


async def test_record_and_read_session_trace(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    e = TraceEvent(session_id="s1", component="x", kind=EventKind.SESSION_STARTED)
    await mgr.record(e)
    events = await mgr.read_session_trace("s1")
    assert events == [e]


async def test_save_and_get_session(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    s = Session(user_request="x")
    await mgr.save_session(s)
    assert await mgr.get_session(s.session_id) == s


async def test_knowledge_facade(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    item = Knowledge(kind=KnowledgeKind.REFLECTION, title="lesson", body="don't mock the db")
    await mgr.add_knowledge(item)
    assert await mgr.get_knowledge(item.knowledge_id) == item
    assert await mgr.list_knowledge_by_kind(KnowledgeKind.REFLECTION) == [item]


async def test_recall_knowledge(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    a = Knowledge(kind=KnowledgeKind.PAPER, title="binder paper", body="paper body")
    b = Knowledge(kind=KnowledgeKind.PAPER, title="enzyme paper", body="enzyme body")
    await mgr.add_knowledge(a)
    await mgr.add_knowledge(b)
    out = await mgr.recall("binder", store="knowledge")
    assert {r.knowledge_id for r in out} == {a.knowledge_id}  # type: ignore[union-attr]


async def test_recall_trace(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    target = TraceEvent(
        session_id="s1",
        component="x",
        kind=EventKind.PLAN_PRODUCED,
        payload={"goal": "binder_alpha"},
    )
    decoy = TraceEvent(
        session_id="s1",
        component="x",
        kind=EventKind.BRANCH_SPAWNED,
        payload={"unrelated": True},
    )
    await mgr.record(target)
    await mgr.record(decoy)
    hits = await mgr.recall("binder_alpha", store="trace", session_id="s1")
    assert any(h.event_id == target.event_id for h in hits)  # type: ignore[union-attr]


async def test_recall_trace_requires_sqlite_store(tmp_path: Path) -> None:
    """An InMemoryTraceStore can't satisfy FTS5 recall — must raise loudly."""
    mgr = MemoryManager(
        knowledge=SQLiteKnowledgeStore(tmp_path / "k.db"),
        sessions=InMemorySessionStore(),
        traces=InMemoryTraceStore(),
    )
    with pytest.raises(NotImplementedError):
        await mgr.recall("anything", store="trace")


async def test_compact_session_no_op_below_threshold(tmp_path: Path) -> None:
    mgr = _manager(tmp_path, threshold=10)
    e = TraceEvent(session_id="s1", component="x", kind=EventKind.SESSION_STARTED)
    await mgr.record(e)
    assert await mgr.compact_session("s1") is None


async def test_compact_session_runs_above_threshold(tmp_path: Path) -> None:
    mgr = _manager(tmp_path, threshold=2)
    for kind in (
        EventKind.SESSION_STARTED,
        EventKind.PLAN_PRODUCED,
        EventKind.SESSION_ENDED,
    ):
        await mgr.record(TraceEvent(session_id="s1", component="x", kind=kind))
    result = await mgr.compact_session("s1")
    assert result is not None
    assert result.session_id == "s1"
    assert result.compacted_event_count == 3


async def test_compact_unknown_session_returns_none(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    assert await mgr.compact_session("never-existed") is None


async def test_compact_force_below_threshold(tmp_path: Path) -> None:
    mgr = _manager(tmp_path, threshold=99)
    await mgr.record(TraceEvent(session_id="s1", component="x", kind=EventKind.SESSION_STARTED))
    result = await mgr.compact_session("s1", force=True)
    assert result is not None
    assert result.compacted_event_count == 1

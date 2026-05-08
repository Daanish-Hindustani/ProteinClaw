"""Tests for SQLiteTraceStore — persistence, ordering, FTS5 search, Protocol conformance."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.common.logging import EventKind, TraceEvent
from proteinclaw.memory.trace_store import SQLiteTraceStore, TraceStore


def _event(
    *,
    session_id: str,
    component: str,
    kind: EventKind,
    branch_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> TraceEvent:
    return TraceEvent(
        session_id=session_id,
        component=component,
        kind=kind,
        branch_id=branch_id,
        payload=payload or {},
    )


def test_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(SQLiteTraceStore(tmp_path / "t.db"), TraceStore)


async def test_append_and_read_session_preserves_insertion_order(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "t.db")
    e1 = _event(session_id="s1", component="orchestrator", kind=EventKind.SESSION_STARTED)
    e2 = _event(session_id="s1", component="planner", kind=EventKind.PLAN_PRODUCED)
    e3 = _event(session_id="s2", component="orchestrator", kind=EventKind.SESSION_STARTED)
    e4 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_SPAWNED)
    for e in (e1, e2, e3, e4):
        await store.append(e)
    s1 = await store.read_session("s1")
    assert [e.event_id for e in s1] == [e1.event_id, e2.event_id, e4.event_id]
    s2 = await store.read_session("s2")
    assert [e.event_id for e in s2] == [e3.event_id]


async def test_read_branch_filters(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "t.db")
    e1 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_SPAWNED, branch_id="b1")
    e2 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_SPAWNED, branch_id="b2")
    e3 = _event(
        session_id="s1",
        component="agent",
        kind=EventKind.BRANCH_COMPLETED,
        branch_id="b1",
    )
    for e in (e1, e2, e3):
        await store.append(e)
    b1 = await store.read_branch("b1")
    assert [e.event_id for e in b1] == [e1.event_id, e3.event_id]


async def test_persists_across_instances(tmp_path: Path) -> None:
    """Open the same DB file twice and confirm events round-trip."""
    db = tmp_path / "t.db"
    writer = SQLiteTraceStore(db)
    e = _event(
        session_id="s1",
        component="orchestrator",
        kind=EventKind.SESSION_STARTED,
        payload={"user_request": "design a binder"},
    )
    await writer.append(e)

    reader = SQLiteTraceStore(db)
    events = await reader.read_session("s1")
    assert events == [e]
    assert events[0].payload["user_request"] == "design a binder"


async def test_fts5_search_finds_matching_payload(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "t.db")
    target = _event(
        session_id="s1",
        component="orchestrator",
        kind=EventKind.PLAN_PRODUCED,
        payload={"task_count": 1, "task_ids": ["binder_design_alpha"]},
    )
    decoy = _event(
        session_id="s1",
        component="agent",
        kind=EventKind.BRANCH_SPAWNED,
        payload={"fanout_index": 0},
    )
    await store.append(target)
    await store.append(decoy)
    hits = await store.search("binder_design_alpha")
    assert any(h.event_id == target.event_id for h in hits)
    assert all(h.event_id != decoy.event_id for h in hits)


async def test_fts5_search_session_scope(tmp_path: Path) -> None:
    store = SQLiteTraceStore(tmp_path / "t.db")
    a = _event(
        session_id="alpha",
        component="orchestrator",
        kind=EventKind.PLAN_PRODUCED,
        payload={"goal": "binder_design"},
    )
    b = _event(
        session_id="beta",
        component="orchestrator",
        kind=EventKind.PLAN_PRODUCED,
        payload={"goal": "binder_design"},
    )
    await store.append(a)
    await store.append(b)
    only_alpha = await store.search("binder_design", session_id="alpha")
    assert {h.event_id for h in only_alpha} == {a.event_id}

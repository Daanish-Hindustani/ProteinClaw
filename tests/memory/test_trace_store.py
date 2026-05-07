"""Tests for memory/trace_store.py — Protocol conformance, ordering, replay, JSONL persistence."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from proteinclaw.common.logging import EventKind, TraceEvent
from proteinclaw.memory.trace_store import (
    InMemoryTraceStore,
    JsonlTraceStore,
    TraceStore,
)


def _event(
    *,
    session_id: str,
    component: str,
    kind: EventKind,
    branch_id: str | None = None,
) -> TraceEvent:
    return TraceEvent(
        session_id=session_id,
        component=component,
        kind=kind,
        branch_id=branch_id,
    )


def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemoryTraceStore(), TraceStore)


def test_jsonl_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(JsonlTraceStore(tmp_path / "trace.jsonl"), TraceStore)


@pytest.mark.parametrize(
    "store_factory",
    [
        pytest.param(lambda _tmp: InMemoryTraceStore(), id="inmemory"),
        pytest.param(
            lambda tmp: JsonlTraceStore(tmp / f"{uuid4()}.jsonl"),
            id="jsonl",
        ),
    ],
)
async def test_append_then_read_session_preserves_order(
    tmp_path: Path,
    store_factory,  # type: ignore[no-untyped-def]
) -> None:
    store = store_factory(tmp_path)
    e1 = _event(session_id="s1", component="orchestrator", kind=EventKind.SESSION_STARTED)
    e2 = _event(session_id="s1", component="planner", kind=EventKind.PLAN_PRODUCED)
    e3 = _event(session_id="s2", component="orchestrator", kind=EventKind.SESSION_STARTED)
    for e in (e1, e2, e3):
        await store.append(e)
    s1_events = await store.read_session("s1")
    assert [e.event_id for e in s1_events] == [e1.event_id, e2.event_id]
    s2_events = await store.read_session("s2")
    assert [e.event_id for e in s2_events] == [e3.event_id]


async def test_read_session_unknown_returns_empty() -> None:
    store = InMemoryTraceStore()
    assert await store.read_session("never-existed") == []


async def test_read_branch_filters_correctly() -> None:
    store = InMemoryTraceStore()
    e1 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_SPAWNED, branch_id="b1")
    e2 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_SPAWNED, branch_id="b2")
    e3 = _event(session_id="s1", component="agent", kind=EventKind.BRANCH_COMPLETED, branch_id="b1")
    for e in (e1, e2, e3):
        await store.append(e)
    b1_events = await store.read_branch("b1")
    assert [e.event_id for e in b1_events] == [e1.event_id, e3.event_id]


async def test_jsonl_persists_across_instances(tmp_path: Path) -> None:
    """Simulate a process restart: a second store reading the same file sees the events."""
    path = tmp_path / "trace.jsonl"
    writer = JsonlTraceStore(path)
    e = _event(session_id="s1", component="orchestrator", kind=EventKind.SESSION_STARTED)
    await writer.append(e)

    reader = JsonlTraceStore(path)
    events = await reader.read_session("s1")
    assert events == [e]


async def test_replay_reconstructs_session() -> None:
    """Replay correctness: emitting events in order yields a stable, ordered history."""
    store = InMemoryTraceStore()
    expected_kinds = [
        EventKind.SESSION_STARTED,
        EventKind.REQUEST_RECEIVED,
        EventKind.PLAN_PRODUCED,
        EventKind.BRANCH_SPAWNED,
        EventKind.TOOL_INVOKED,
        EventKind.TOOL_SUCCEEDED,
        EventKind.BRANCH_COMPLETED,
        EventKind.EVALUATION_PRODUCED,
        EventKind.SESSION_ENDED,
    ]
    for kind in expected_kinds:
        await store.append(_event(session_id="s1", component="x", kind=kind))
    replayed = await store.read_session("s1")
    assert [e.kind for e in replayed] == expected_kinds

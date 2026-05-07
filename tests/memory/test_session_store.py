"""Tests for memory/session_store.py — immutable updates, Protocol, save/get round-trip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proteinclaw.memory.session_store import (
    InMemorySessionStore,
    Session,
    SessionStore,
)


def test_session_defaults() -> None:
    s = Session(user_request="design a binder")
    assert s.session_id
    assert s.task_ids == ()
    assert s.active_branch_ids == ()
    assert s.iterations_used == 0
    assert s.ended_at is None


def test_session_is_frozen() -> None:
    s = Session(user_request="x")
    with pytest.raises(ValidationError):
        s.iterations_used = 1  # type: ignore[misc]


def test_with_task_appends_immutably() -> None:
    s = Session(user_request="x")
    s2 = s.with_task("t1").with_task("t2")
    assert s.task_ids == ()  # original untouched
    assert s2.task_ids == ("t1", "t2")


def test_with_active_branches_replaces() -> None:
    s = Session(user_request="x").with_active_branches(("b1", "b2"))
    s2 = s.with_active_branches(("b3",))
    assert s.active_branch_ids == ("b1", "b2")
    assert s2.active_branch_ids == ("b3",)


def test_with_iteration_increment() -> None:
    s = Session(user_request="x")
    s3 = s.with_iteration_increment().with_iteration_increment().with_iteration_increment()
    assert s.iterations_used == 0
    assert s3.iterations_used == 3


def test_finalized_clears_active_and_sets_payload_and_ended() -> None:
    s = Session(user_request="x").with_active_branches(("b1",))
    done = s.finalized({"result": "ok"})
    assert done.final_payload == {"result": "ok"}
    assert done.ended_at is not None
    assert done.active_branch_ids == ()
    # Original untouched.
    assert s.final_payload is None
    assert s.ended_at is None


def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemorySessionStore(), SessionStore)


async def test_save_and_get_round_trip() -> None:
    store = InMemorySessionStore()
    s = Session(user_request="design a binder")
    await store.save(s)
    got = await store.get(s.session_id)
    assert got == s


async def test_get_unknown_returns_none() -> None:
    store = InMemorySessionStore()
    assert await store.get("nope") is None


async def test_save_replaces_previous_snapshot() -> None:
    store = InMemorySessionStore()
    s = Session(user_request="x")
    await store.save(s)
    s2 = s.with_iteration_increment()
    await store.save(s2)
    assert (await store.get(s.session_id)) == s2

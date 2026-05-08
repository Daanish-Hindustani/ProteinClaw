"""Tests for SQLiteSessionStore — upsert, persistence, Protocol conformance."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.memory.session_store import (
    Session,
    SessionStore,
    SQLiteSessionStore,
)


def test_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(SQLiteSessionStore(tmp_path / "s.db"), SessionStore)


async def test_save_and_get_round_trip(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "s.db")
    s = Session(user_request="design a binder")
    await store.save(s)
    got = await store.get(s.session_id)
    assert got == s


async def test_get_unknown_returns_none(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "s.db")
    assert await store.get("nope") is None


async def test_save_upsert_replaces_snapshot(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "s.db")
    s = Session(user_request="x")
    await store.save(s)
    s2 = s.with_iteration_increment()
    await store.save(s2)
    got = await store.get(s.session_id)
    assert got == s2
    assert got is not None
    assert got.iterations_used == 1


async def test_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    writer = SQLiteSessionStore(db)
    s = Session(user_request="recover me")
    await writer.save(s)
    reader = SQLiteSessionStore(db)
    assert (await reader.get(s.session_id)) == s

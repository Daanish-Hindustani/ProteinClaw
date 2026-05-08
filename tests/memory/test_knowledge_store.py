"""Tests for SQLiteKnowledgeStore — add/get/list/search across kinds."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.memory.knowledge_store import (
    Knowledge,
    KnowledgeKind,
    SQLiteKnowledgeStore,
)


def _entry(
    *,
    kind: KnowledgeKind = KnowledgeKind.DOMAIN_CONCEPT,
    title: str = "x",
    body: str = "y",
    tags: tuple[str, ...] = (),
) -> Knowledge:
    return Knowledge(kind=kind, title=title, body=body, tags=tags)


async def test_add_and_get(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "k.db")
    item = _entry(title="hotspot", body="A hotspot is...", tags=("binder",))
    await store.add(item)
    got = await store.get(item.knowledge_id)
    assert got == item


async def test_get_unknown_returns_none(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "k.db")
    assert await store.get("nope") is None


async def test_list_by_kind_filters_and_orders_newest_first(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "k.db")
    a = _entry(kind=KnowledgeKind.PAPER, title="A")
    b = _entry(kind=KnowledgeKind.PAPER, title="B")
    c = _entry(kind=KnowledgeKind.DOMAIN_CONCEPT, title="C")
    await store.add(a)
    await store.add(b)
    await store.add(c)
    papers = await store.list_by_kind(KnowledgeKind.PAPER)
    assert {p.title for p in papers} == {"A", "B"}
    concepts = await store.list_by_kind(KnowledgeKind.DOMAIN_CONCEPT)
    assert [k.title for k in concepts] == ["C"]


async def test_search_finds_in_title_and_body(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "k.db")
    a = _entry(
        kind=KnowledgeKind.DOMAIN_CONCEPT,
        title="hotspot residues",
        body="Defined as exposed conserved residues",
    )
    b = _entry(
        kind=KnowledgeKind.PAPER,
        title="Backbone diffusion",
        body="RFdiffusion is a backbone generation model",
    )
    await store.add(a)
    await store.add(b)
    out = await store.search("hotspot")
    assert {r.knowledge_id for r in out} == {a.knowledge_id}
    out2 = await store.search("RFdiffusion")
    assert {r.knowledge_id for r in out2} == {b.knowledge_id}


async def test_search_kind_filter(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "k.db")
    paper = _entry(kind=KnowledgeKind.PAPER, title="binder paper", body="...")
    reflection = _entry(
        kind=KnowledgeKind.REFLECTION,
        title="binder lessons",
        body="learned that contigs matter",
    )
    await store.add(paper)
    await store.add(reflection)
    only_papers = await store.search("binder", kind=KnowledgeKind.PAPER)
    assert {r.knowledge_id for r in only_papers} == {paper.knowledge_id}


async def test_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    writer = SQLiteKnowledgeStore(db)
    item = _entry(title="persistent", body="b")
    await writer.add(item)
    reader = SQLiteKnowledgeStore(db)
    assert (await reader.get(item.knowledge_id)) == item

"""Knowledge Store: curated long-lived knowledge with FTS5 search.

Holds four kinds of records:

- ``paper``: scientific references and notes drawn from literature.
- ``tool_doc``: extended documentation for protein-design tools (the
  registered tool descriptions are short by design; long-form notes
  live here).
- ``domain_concept``: curated explanations of domain terms (binders,
  contigs, hotspots, scaffolds, etc.) the orchestrator can surface to
  sub-agents.
- ``reflection``: short curated lessons written by the Evolution
  Service after runs. These are the input GEPA / Feedback Descent
  consume in Phase 7.

The store wraps a SQLite database with FTS5 over `(title, body, tags)`.
Embeddings deferred per PLAN.md §Phase 5; FTS5 keyword search is
sufficient at our current scale.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.memory._sqlite import execute_script, open_connection


class KnowledgeKind(StrEnum):
    """Type tag for knowledge entries."""

    PAPER = "paper"
    TOOL_DOC = "tool_doc"
    DOMAIN_CONCEPT = "domain_concept"
    REFLECTION = "reflection"


class Knowledge(BaseModel):
    """One immutable knowledge entry.

    Attributes:
        knowledge_id: Unique id; UUIDv4 by default.
        kind: One of `KnowledgeKind`.
        title: Short label.
        body: Markdown body. Searchable.
        tags: Free-form tags joined into the FTS index.
        source_url: Optional canonical URL.
        created_at: UTC creation time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: KnowledgeKind
    title: str
    body: str
    tags: tuple[str, ...] = ()
    source_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


_KNOWLEDGE_DDL = """
CREATE TABLE IF NOT EXISTS knowledge (
    knowledge_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    knowledge_id UNINDEXED,
    kind,
    title,
    body,
    tags
);
"""


class SQLiteKnowledgeStore:
    """SQLite + FTS5 knowledge store."""

    def __init__(self, path: Path) -> None:
        """Bind the store to `path`. Schema is created on first connect."""
        self._path = path
        self._lock = asyncio.Lock()
        execute_script(path, _KNOWLEDGE_DDL)

    async def add(self, item: Knowledge) -> None:
        """Insert one knowledge entry into the table and FTS index."""
        async with self._lock:
            await asyncio.to_thread(self._add_sync, item)

    def _add_sync(self, item: Knowledge) -> None:
        """Synchronous insert helper."""
        tags_str = " ".join(item.tags)
        import json as _json

        with open_connection(self._path) as con:
            con.execute(
                """INSERT INTO knowledge(knowledge_id, kind, title, body,
                                          tags_json, source_url, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.knowledge_id,
                    item.kind.value,
                    item.title,
                    item.body,
                    _json.dumps(list(item.tags)),
                    item.source_url,
                    item.created_at.isoformat(),
                ),
            )
            con.execute(
                """INSERT INTO knowledge_fts(knowledge_id, kind, title, body, tags)
                   VALUES (?, ?, ?, ?, ?)""",
                (item.knowledge_id, item.kind.value, item.title, item.body, tags_str),
            )

    async def get(self, knowledge_id: str) -> Knowledge | None:
        """Return the entry with the given id, or None."""
        return await asyncio.to_thread(self._get_sync, knowledge_id)

    def _get_sync(self, knowledge_id: str) -> Knowledge | None:
        """Synchronous lookup helper."""
        with open_connection(self._path) as con:
            row = con.execute(
                """SELECT knowledge_id, kind, title, body, tags_json,
                          source_url, created_at
                   FROM knowledge WHERE knowledge_id = ?""",
                (knowledge_id,),
            ).fetchone()
        return _row_to_knowledge(row) if row is not None else None

    async def list_by_kind(self, kind: KnowledgeKind) -> list[Knowledge]:
        """Return all entries of the given kind, newest first."""
        return await asyncio.to_thread(self._list_by_kind_sync, kind)

    def _list_by_kind_sync(self, kind: KnowledgeKind) -> list[Knowledge]:
        """Synchronous filter-by-kind helper."""
        with open_connection(self._path) as con:
            rows = con.execute(
                """SELECT knowledge_id, kind, title, body, tags_json,
                          source_url, created_at
                   FROM knowledge WHERE kind = ?
                   ORDER BY created_at DESC""",
                (kind.value,),
            ).fetchall()
        return [_row_to_knowledge(r) for r in rows]

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind | None = None,
        limit: int = 20,
    ) -> list[Knowledge]:
        """Full-text search across title/body/tags.

        Args:
            query: FTS5 query string.
            kind: Optional kind filter.
            limit: Maximum results.

        Returns:
            Matches ordered by FTS5 relevance (`rank`).
        """
        return await asyncio.to_thread(self._search_sync, query, kind, limit)

    def _search_sync(self, query: str, kind: KnowledgeKind | None, limit: int) -> list[Knowledge]:
        """Synchronous FTS5 search helper."""
        sql = """SELECT k.knowledge_id, k.kind, k.title, k.body, k.tags_json,
                      k.source_url, k.created_at
               FROM knowledge_fts f
               JOIN knowledge k ON k.knowledge_id = f.knowledge_id
               WHERE knowledge_fts MATCH ?"""
        params: list[Any] = [query]
        if kind is not None:
            sql += " AND k.kind = ?"
            params.append(kind.value)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with open_connection(self._path) as con:
            rows = con.execute(sql, params).fetchall()
        return [_row_to_knowledge(r) for r in rows]


def _row_to_knowledge(row: sqlite3.Row) -> Knowledge:
    """Hydrate a SQLite row into the immutable `Knowledge` model."""
    import json as _json

    return Knowledge(
        knowledge_id=row["knowledge_id"],
        kind=KnowledgeKind(row["kind"]),
        title=row["title"],
        body=row["body"],
        tags=tuple(_json.loads(row["tags_json"])),
        source_url=row["source_url"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )

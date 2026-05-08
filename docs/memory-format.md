# Memory Format

Three SQLite stores backed by FTS5 where retrieval matters. Schemas live
in `src/proteinclaw/memory/{trace,session,knowledge}_store.py` as
module-level DDL constants and run on first connect via `execute_script()`
(idempotent — `CREATE TABLE IF NOT EXISTS`).

| Store | Module | Purpose | FTS5 |
|---|---|---|---|
| Trace Store | `trace_store.py` | Append-only event log | Yes |
| Session Store | `session_store.py` | Live run state, one snapshot per session | No |
| Knowledge Store | `knowledge_store.py` | Curated long-lived knowledge (papers, tool docs, domain concepts, reflections) | Yes |

## Trace Store

<!-- AUTO-GENERATED:trace-ddl (source: src/proteinclaw/memory/trace_store.py::_TRACE_DDL) -->

```sql
CREATE TABLE trace_events (
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
CREATE INDEX idx_trace_session ON trace_events(session_id, insertion_order);
CREATE INDEX idx_trace_branch  ON trace_events(branch_id, insertion_order);

CREATE VIRTUAL TABLE trace_events_fts USING fts5(
    event_id UNINDEXED,
    session_id,
    component,
    kind,
    payload_text
);
```

<!-- /AUTO-GENERATED:trace-ddl -->

`insertion_order` is the canonical replay sequence — independent of
timestamps. Events are inserted into both `trace_events` and
`trace_events_fts` atomically per append. Replay reads in `ORDER BY
insertion_order ASC`.

`SQLiteTraceStore.search(query, session_id=None, limit=50)` runs FTS5
MATCH over `payload_text`, sorted by `rank`, optionally scoped to a
session.

## Session Store

<!-- AUTO-GENERATED:session-ddl (source: src/proteinclaw/memory/session_store.py::_SESSION_DDL) -->

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

<!-- /AUTO-GENERATED:session-ddl -->

The `Session` model is serialized as JSON in `snapshot_json`. Saves
UPSERT — there is only ever one current snapshot per session id. The
historical lineage of a session is reconstructable from the Trace Store,
not by versioning this table.

## Knowledge Store

<!-- AUTO-GENERATED:knowledge-ddl (source: src/proteinclaw/memory/knowledge_store.py::_KNOWLEDGE_DDL) -->

```sql
CREATE TABLE knowledge (
    knowledge_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_knowledge_kind ON knowledge(kind);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    knowledge_id UNINDEXED,
    kind,
    title,
    body,
    tags
);
```

<!-- /AUTO-GENERATED:knowledge-ddl -->

`KnowledgeKind` values: `paper`, `tool_doc`, `domain_concept`, `reflection`.
The reflections table is the input the Evolution Service consumes in
Phase 7 — Feedback Descent's reflective mutation reads from here.

## SQLite pragmas

Set on every new connection by `_sqlite.open_connection()`:

- `journal_mode=WAL` — concurrent readers + single writer.
- `foreign_keys=ON` — off by default in SQLite (footgun).
- `synchronous=NORMAL` — safe with WAL, faster than `FULL`.

Connections are short-lived: every operation opens a new connection and
closes it via the `with` context. Async safety is provided by per-store
`asyncio.Lock`s plus `asyncio.to_thread` for the blocking SQL calls.

## MemoryManager facade

`MemoryManager` (`memory_manager.py`) routes to the right store:

| Call | Destination |
|---|---|
| `record(event)` | TraceStore.append |
| `read_session_trace / read_branch_trace` | TraceStore reads |
| `save_session / get_session` | SessionStore |
| `add_knowledge / get_knowledge / list_knowledge_by_kind` | KnowledgeStore |
| `recall(query, store="knowledge"\|"trace")` | FTS5 search on the chosen store |
| `compact_session(id, force=False)` | TraceStore + Compactor |

### Known gap: trace recall is SQLite-only

`recall(store="trace", …)` raises `NotImplementedError` unless the bound
`TraceStore` is a `SQLiteTraceStore`. The `TraceStore` Protocol does not
yet declare a `search()` method, so `InMemoryTraceStore` and
`JsonlTraceStore` cannot satisfy the recall path. Production use is
unaffected (the CLI binds `SQLiteTraceStore`); tests and short-lived
runs that use the in-memory store must call `read_session` /
`read_branch` and filter in Python.

Tracked fix: promote `search()` to the Protocol and add linear-scan
implementations for the in-memory and JSONL stores so `MemoryManager`
no longer has to `isinstance`-check the backend.

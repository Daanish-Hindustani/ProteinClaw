# Memory Format

> Stub. Authored in Phase 5.

Three SQLite stores (FTS5 enabled where noted):

| Store | Purpose | FTS5 |
|---|---|---|
| Knowledge Store | Curated domain knowledge, papers, tool docs, reflections | Yes |
| Session Store | Live run state, active branches | No |
| Trace Store | Append-only event log | Yes |

Reflections (curated lessons from past runs) live as a table inside the Knowledge Store and feed the Evolution Service.

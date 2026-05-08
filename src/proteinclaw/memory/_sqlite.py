"""Shared SQLite helpers used by every memory backend.

Each store opens fresh connections per operation rather than holding a
long-lived one. SQLite's pysqlite driver is sync, so we wrap blocking
calls in `asyncio.to_thread` to keep the event loop happy. An asyncio
lock per store serializes writes from concurrent tasks.

Schema bootstrap is idempotent: every connection runs `executescript()`
on the relevant DDL. It's cheap and means we don't need a separate
migration step for the Phase 5 footprint.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Pragmas applied on every connection. WAL is the right default for
# concurrent readers + a single writer; foreign_keys is off by default
# in SQLite which is a footgun.
_CONNECTION_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA synchronous=NORMAL;",
)


def open_connection(path: Path) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Caller owns the lifecycle. Use as a context manager (``with conn:``)
    so commits and rollbacks happen automatically.
    """
    con = sqlite3.connect(path, isolation_level=None)  # autocommit-style
    for p in _CONNECTION_PRAGMAS:
        con.execute(p)
    con.row_factory = sqlite3.Row
    return con


def execute_script(path: Path, ddl: str) -> None:
    """Run idempotent DDL against the database at `path`."""
    with open_connection(path) as con:
        con.executescript(ddl)

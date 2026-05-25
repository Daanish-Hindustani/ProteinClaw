"""SQLite persistence for proteinclaw runs (PRD §6.9).

Three tables: ``runs``, ``designs``, ``agent_steps``. Connection is
process-local and not pooled — the CLI opens it on demand and closes on
exit. For long-running campaigns ``record_step()`` is called many times
in sequence; SQLite handles that fine without per-call connection churn.

Top pLDDT is **not** denormalized on ``runs`` (PRD §6.9): derive from
``designs.plddt_af2_complex`` via the helper queries below.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_DB = Path("~/.proteinclaw/runs.db").expanduser()

# Bump when adding a non-backward-compatible schema change. Migration logic
# lives in `migrate()` below — keep additions idempotent.
CURRENT_SCHEMA_VERSION = 3

# Columns added to ``runs`` after v1, applied idempotently to existing DBs the
# same way as ``_DESIGNS_ADDED_COLUMNS``. ``pid`` records the OS process id of
# the ``proteinclaw run`` driver so ``proteinclaw cancel`` can signal it.
_RUNS_ADDED_COLUMNS = {
    "pid": "INTEGER",
}

# Columns added after v1. Applied idempotently to existing DBs via ALTER TABLE
# (guarded by a PRAGMA check) so upgrades don't lose historical runs.
_DESIGNS_ADDED_COLUMNS = {
    "ipsae": "REAL",
    "iptm": "REAL",
    "pdockq": "REAL",
    "lis": "REAL",
}

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    target_pdb_id   TEXT,
    target_chain    TEXT,
    target_crop     TEXT,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    status          TEXT NOT NULL,        -- running | completed | failed
    num_designs     INTEGER DEFAULT 0,
    output_dir      TEXT NOT NULL,
    agent_model     TEXT,
    git_sha         TEXT,
    total_cost_usd  REAL,
    num_turns       INTEGER,
    elapsed_s       REAL,
    failure_reason  TEXT
);

CREATE TABLE IF NOT EXISTS designs (
    design_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    rank                INTEGER,
    plddt_esm_monomer   REAL,
    plddt_af2_complex   REAL,
    ipsae               REAL,
    iptm                REAL,
    pdockq              REAL,
    lis                 REAL,
    pdb_path            TEXT,
    fasta_path          TEXT,
    sequence            TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS agent_steps (
    step_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT NOT NULL,
    step_idx             INTEGER NOT NULL,
    role                 TEXT NOT NULL,   -- user | assistant_text | tool_use | tool_result
    content              TEXT,
    tool                 TEXT,
    tool_args            TEXT,
    tool_result_summary  TEXT,
    timestamp            REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_target  ON runs(target_pdb_id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_designs_run  ON designs(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_steps_run    ON agent_steps(run_id, step_idx);
"""


# ---------------------------------------------------------------------------
# connection + migration
# ---------------------------------------------------------------------------


def open_db(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and migrate) the runs DB. Caller owns ``.close()``."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def _ensure_designs_columns(conn: sqlite3.Connection) -> None:
    """Add post-v1 ``designs`` columns to an existing DB if missing.

    ``CREATE TABLE IF NOT EXISTS`` won't alter a table that already exists, so
    DBs created under v1 need the new metric columns backfilled. Guarded by
    ``PRAGMA table_info`` so it's safe to run on every open.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(designs)")}
    for col, decl in _DESIGNS_ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE designs ADD COLUMN {col} {decl}")


def _ensure_runs_columns(conn: sqlite3.Connection) -> None:
    """Add post-v1 ``runs`` columns to an existing DB if missing (see above)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    for col, decl in _RUNS_ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending schema migrations. Idempotent. Returns the new version."""
    conn.executescript(_SCHEMA_V1)
    _ensure_designs_columns(conn)
    _ensure_runs_columns(conn)
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.commit()
        return CURRENT_SCHEMA_VERSION
    if int(row[0]) < CURRENT_SCHEMA_VERSION:
        conn.execute(
            "UPDATE schema_version SET version = ?", (CURRENT_SCHEMA_VERSION,)
        )
    conn.commit()
    return CURRENT_SCHEMA_VERSION


def schema_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    return int(row[0]) if row else 0


@contextmanager
def connect(path: Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Context manager for open_db — commits on clean exit, rolls back on error."""
    conn = open_db(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def record_run_start(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    session_id: str,
    prompt: str,
    output_dir: str,
    agent_model: Optional[str] = None,
    git_sha: Optional[str] = None,
    started_at: Optional[float] = None,
    pid: Optional[int] = None,
) -> None:
    """Insert a row for a run that just kicked off. Status starts ``running``.

    ``pid`` is the OS process id of the driver process; ``proteinclaw cancel``
    uses it to signal an in-flight run. Left ``NULL`` for runs that don't need
    to be cancellable (e.g. in tests).
    """
    conn.execute(
        """
        INSERT INTO runs (
            run_id, session_id, prompt, output_dir,
            agent_model, git_sha, started_at, status, pid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)
        """,
        (
            run_id,
            session_id,
            prompt,
            output_dir,
            agent_model,
            git_sha,
            started_at if started_at is not None else time.time(),
            pid,
        ),
    )
    conn.commit()


def record_run_end(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,                           # 'completed', 'failed', or 'cancelled'
    ended_at: Optional[float] = None,
    num_designs: int = 0,
    total_cost_usd: Optional[float] = None,
    num_turns: Optional[int] = None,
    elapsed_s: Optional[float] = None,
    failure_reason: Optional[str] = None,
    target_pdb_id: Optional[str] = None,
    target_chain: Optional[str] = None,
    target_crop: Optional[str] = None,
) -> None:
    """Update the run row with terminal metadata."""
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError(
            f"status must be 'completed', 'failed', or 'cancelled', got {status!r}"
        )
    conn.execute(
        """
        UPDATE runs SET
            status = ?,
            ended_at = ?,
            num_designs = ?,
            total_cost_usd = ?,
            num_turns = ?,
            elapsed_s = ?,
            failure_reason = ?,
            target_pdb_id = COALESCE(?, target_pdb_id),
            target_chain  = COALESCE(?, target_chain),
            target_crop   = COALESCE(?, target_crop)
        WHERE run_id = ?
        """,
        (
            status,
            ended_at if ended_at is not None else time.time(),
            num_designs,
            total_cost_usd,
            num_turns,
            elapsed_s,
            failure_reason,
            target_pdb_id,
            target_chain,
            target_crop,
            run_id,
        ),
    )
    conn.commit()


def record_design(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    rank: int,
    plddt_esm_monomer: Optional[float] = None,
    plddt_af2_complex: Optional[float] = None,
    ipsae: Optional[float] = None,
    iptm: Optional[float] = None,
    pdockq: Optional[float] = None,
    lis: Optional[float] = None,
    pdb_path: Optional[str] = None,
    fasta_path: Optional[str] = None,
    sequence: Optional[str] = None,
) -> int:
    """Insert one ranked design. Returns the assigned design_id."""
    cur = conn.execute(
        """
        INSERT INTO designs
            (run_id, rank, plddt_esm_monomer, plddt_af2_complex,
             ipsae, iptm, pdockq, lis,
             pdb_path, fasta_path, sequence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            rank,
            plddt_esm_monomer,
            plddt_af2_complex,
            ipsae,
            iptm,
            pdockq,
            lis,
            pdb_path,
            fasta_path,
            sequence,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def record_step(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_idx: int,
    role: str,                              # 'user' | 'assistant_text' | 'tool_use' | 'tool_result'
    content: Optional[str] = None,
    tool: Optional[str] = None,
    tool_args: Optional[Any] = None,
    tool_result_summary: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> None:
    """Append one agent-loop event."""
    args_str: Optional[str]
    if tool_args is None or isinstance(tool_args, str):
        args_str = tool_args
    else:
        args_str = json.dumps(tool_args, default=str, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO agent_steps
            (run_id, step_idx, role, content, tool,
             tool_args, tool_result_summary, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            step_idx,
            role,
            content,
            tool,
            args_str,
            tool_result_summary,
            timestamp if timestamp is not None else time.time(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def list_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    target: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Most-recent-first. ``target`` filters by exact ``target_pdb_id``."""
    if target is not None:
        cur = conn.execute(
            "SELECT * FROM runs WHERE target_pdb_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (target, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in cur.fetchall()]


def get_run(
    conn: sqlite3.Connection, run_id: str
) -> Optional[dict[str, Any]]:
    """Full run record: the ``runs`` row + its designs (ordered by rank)."""
    cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    if row is None:
        return None
    designs = conn.execute(
        "SELECT * FROM designs WHERE run_id = ? "
        "ORDER BY (rank IS NULL), rank, design_id",
        (run_id,),
    ).fetchall()
    return {"run": dict(row), "designs": [dict(d) for d in designs]}


def top_plddt(
    conn: sqlite3.Connection, run_id: str
) -> Optional[float]:
    """Derive max AF2 complex pLDDT for the run (PRD §6.9 — not denormalized)."""
    cur = conn.execute(
        "SELECT MAX(plddt_af2_complex) FROM designs WHERE run_id = ?",
        (run_id,),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def count_steps(conn: sqlite3.Connection, run_id: str) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM agent_steps WHERE run_id = ?", (run_id,)
    )
    return int(cur.fetchone()[0])


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_DB",
    "connect",
    "count_steps",
    "get_run",
    "list_runs",
    "migrate",
    "open_db",
    "record_design",
    "record_run_end",
    "record_run_start",
    "record_step",
    "schema_version",
    "top_plddt",
]

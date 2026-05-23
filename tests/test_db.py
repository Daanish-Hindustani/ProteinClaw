"""SQLite persistence — schema, CRUD, migration, queries."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from proteinclaw import db


@pytest.fixture
def conn(tmp_path: Path):
    c = db.open_db(tmp_path / "runs.db")
    yield c
    c.close()


def test_schema_version_initialised(conn) -> None:
    assert db.schema_version(conn) == db.CURRENT_SCHEMA_VERSION


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "runs.db"
    c1 = db.open_db(p)
    v1 = db.schema_version(c1)
    c1.close()
    c2 = db.open_db(p)
    v2 = db.schema_version(c2)
    c2.close()
    assert v1 == v2 == db.CURRENT_SCHEMA_VERSION


def test_record_run_start_inserts_running_row(conn) -> None:
    db.record_run_start(
        conn,
        run_id="r1",
        session_id="s1",
        prompt="test prompt",
        output_dir="/tmp/runs/r1",
        agent_model="claude-opus-4-7",
    )
    rec = db.get_run(conn, "r1")
    assert rec is not None
    assert rec["run"]["status"] == "running"
    assert rec["run"]["agent_model"] == "claude-opus-4-7"
    assert rec["run"]["ended_at"] is None


def test_record_run_end_updates_status_and_metadata(conn) -> None:
    db.record_run_start(
        conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp"
    )
    db.record_run_end(
        conn,
        "r1",
        status="completed",
        num_designs=8,
        total_cost_usd=1.23,
        num_turns=42,
        elapsed_s=300.5,
        target_pdb_id="5JDS",
        target_chain="A",
        target_crop="18-134",
    )
    r = db.get_run(conn, "r1")["run"]
    assert r["status"] == "completed"
    assert r["num_designs"] == 8
    assert r["total_cost_usd"] == 1.23
    assert r["num_turns"] == 42
    assert r["target_pdb_id"] == "5JDS"
    assert r["target_chain"] == "A"
    assert r["target_crop"] == "18-134"


def test_record_run_end_rejects_bad_status(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    with pytest.raises(ValueError, match="status"):
        db.record_run_end(conn, "r1", status="weird")


def test_record_designs_ordered_by_rank(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    # Insert out of order; get_run should return them sorted by rank.
    db.record_design(conn, run_id="r1", rank=2, plddt_af2_complex=70.0, pdb_path="/p2")
    db.record_design(conn, run_id="r1", rank=1, plddt_af2_complex=85.5, pdb_path="/p1")
    db.record_design(conn, run_id="r1", rank=3, plddt_af2_complex=60.0, pdb_path="/p3")
    designs = db.get_run(conn, "r1")["designs"]
    assert [d["rank"] for d in designs] == [1, 2, 3]
    assert designs[0]["pdb_path"] == "/p1"


def test_top_plddt_derives_max(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    db.record_design(conn, run_id="r1", rank=1, plddt_af2_complex=70.0)
    db.record_design(conn, run_id="r1", rank=2, plddt_af2_complex=92.5)
    db.record_design(conn, run_id="r1", rank=3, plddt_af2_complex=85.0)
    assert db.top_plddt(conn, "r1") == 92.5


def test_top_plddt_none_when_no_designs(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    assert db.top_plddt(conn, "r1") is None


def test_record_step_serialises_dict_args(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s1", prompt="p", output_dir="/tmp")
    db.record_step(
        conn,
        run_id="r1",
        step_idx=0,
        role="tool_use",
        tool="design.rfdiffusion3",
        tool_args={"target_pdb": "/workspace/target.pdb", "num_designs": 4},
    )
    assert db.count_steps(conn, "r1") == 1
    row = conn.execute("SELECT * FROM agent_steps WHERE run_id='r1'").fetchone()
    assert '"num_designs": 4' in row["tool_args"]


def test_list_runs_orders_recent_first_and_limits(conn) -> None:
    for i, t in enumerate([100.0, 200.0, 300.0]):
        db.record_run_start(
            conn,
            run_id=f"r{i}",
            session_id="s",
            prompt=f"p{i}",
            output_dir="/tmp",
            started_at=t,
        )
    rows = db.list_runs(conn, limit=2)
    assert [r["run_id"] for r in rows] == ["r2", "r1"]


def test_list_runs_filter_by_target(conn) -> None:
    db.record_run_start(conn, run_id="r1", session_id="s", prompt="p", output_dir="/tmp")
    db.record_run_end(conn, "r1", status="completed", target_pdb_id="5JDS")
    db.record_run_start(conn, run_id="r2", session_id="s", prompt="p", output_dir="/tmp")
    db.record_run_end(conn, "r2", status="completed", target_pdb_id="6NP9")
    db.record_run_start(conn, run_id="r3", session_id="s", prompt="p", output_dir="/tmp")
    db.record_run_end(conn, "r3", status="completed", target_pdb_id="5JDS")
    rows = db.list_runs(conn, target="5JDS")
    assert sorted(r["run_id"] for r in rows) == ["r1", "r3"]


def test_get_run_missing_returns_none(conn) -> None:
    assert db.get_run(conn, "nope") is None


def test_connect_rollback_on_error(tmp_path: Path) -> None:
    p = tmp_path / "runs.db"
    with pytest.raises(RuntimeError):
        with db.connect(p) as c:
            db.record_run_start(
                c, run_id="r1", session_id="s", prompt="p", output_dir="/tmp"
            )
            raise RuntimeError("boom")
    # The autocommits in record_run_start mean the row survives the rollback;
    # context-manager rollback only covers uncommitted writes. This documents
    # the actual behavior (record_* helpers commit per call) so callers know.
    with db.connect(p) as c:
        assert db.get_run(c, "r1") is not None

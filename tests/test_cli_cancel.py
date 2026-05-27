"""`proteinclaw cancel` — container kill + driver signal + DB status flip.

Docker and process-signalling are stubbed; these tests exercise the control
flow and the DB side-effects, not real `docker kill` / `os.kill`.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proteinclaw import cli, db

runner = CliRunner()


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    """Point `db.connect()` at a throwaway DB for the duration of a test."""
    path = tmp_path / "runs.db"

    @contextlib.contextmanager
    def _connect(*_a, **_k):
        conn = db.open_db(path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    monkeypatch.setattr(db, "connect", _connect)
    return path


def _seed_running_run(path: Path, *, status: str = "running", pid: int | None = 1234) -> None:
    conn = db.open_db(path)
    db.record_run_start(conn, run_id="run-abc", session_id="sess-xyz", prompt="p", output_dir="/tmp", pid=pid)
    if status != "running":
        db.record_run_end(conn, run_id="run-abc", status=status)
    conn.close()


def test_cancel_running_run_kills_signals_and_flips_status(tmp_db, monkeypatch) -> None:
    _seed_running_run(tmp_db)
    calls = {}
    monkeypatch.setattr(cli, "_kill_session_containers", lambda sid: calls.setdefault("sid", sid) or ["c0ffee123456"])
    monkeypatch.setattr(cli, "_terminate_run_process", lambda pid: calls.setdefault("pid", pid) or True)

    result = runner.invoke(cli.app, ["cancel", "run-abc"])

    assert result.exit_code == 0, result.output
    assert calls["sid"] == "sess-xyz"          # container kill targeted the session
    assert calls["pid"] == 1234                 # driver signalled with recorded pid
    assert "Cancelled run run-abc" in result.output
    conn = db.open_db(tmp_db)
    assert db.get_run(conn, "run-abc")["run"]["status"] == "cancelled"
    conn.close()


def test_cancel_non_running_run_is_noop(tmp_db, monkeypatch) -> None:
    _seed_running_run(tmp_db, status="completed")
    killed = monkeypatch.setattr(cli, "_kill_session_containers", lambda sid: pytest.fail("should not kill"))

    result = runner.invoke(cli.app, ["cancel", "run-abc"])

    assert result.exit_code == 0
    assert "not in-flight" in result.output
    conn = db.open_db(tmp_db)
    assert db.get_run(conn, "run-abc")["run"]["status"] == "completed"  # unchanged
    conn.close()


def test_cancel_missing_run_errors(tmp_db) -> None:
    result = runner.invoke(cli.app, ["cancel", "does-not-exist"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_terminate_run_process_handles_null_and_dead_pid() -> None:
    assert cli._terminate_run_process(None) is False
    # A pid that cannot exist → ProcessLookupError/PermissionError → False, no raise.
    assert cli._terminate_run_process(2**30) is False


def test_kill_session_containers_no_docker_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert cli._kill_session_containers("sess-xyz") == []

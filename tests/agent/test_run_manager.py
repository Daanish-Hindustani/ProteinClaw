from __future__ import annotations

import json
from pathlib import Path

import pytest

from proteinclaw.agent.run_manager import RunManager


def test_run_manager_creates_paths_and_metadata(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")

    ctx = manager.create_run(prompt="design", run_id="abc123", session_id="sess123")

    assert ctx.output_dir == tmp_path / "runs" / "abc123"
    assert ctx.workspace == tmp_path / "workspace" / "sess123"
    assert ctx.designs_dir.is_dir()
    assert ctx.trace_jsonl.exists()
    meta = json.loads((ctx.output_dir / "run.json").read_text(encoding="utf-8"))
    assert meta["run_id"] == "abc123"
    assert meta["session_id"] == "sess123"
    assert meta["prompt"] == "design"


def test_run_manager_status_resume_finalize(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    manager.create_run(run_id="r1")

    assert manager.resume_run("r1").status == "running"
    assert manager.finalize_run("r1").status == "completed"
    assert manager.list_runs()[0].run_id == "r1"


def test_run_manager_rejects_invalid_id(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")

    with pytest.raises(ValueError):
        manager.create_run(run_id="../escape")

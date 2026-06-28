"""Core helpers — RunPaths layout, dry-run CLI path."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from proteinclaw.agent.core import _tail_trace_for_stream, mint_run_paths


def test_mint_run_paths_creates_layout(tmp_path: Path) -> None:
    paths = mint_run_paths(tmp_path, run_id="r123", session_id="s123")
    assert paths.run_id == "r123"
    assert paths.session_id == "s123"
    assert paths.output_dir.exists() and paths.output_dir.is_dir()
    assert paths.designs_dir.exists()
    assert paths.output_dir.name == "r123"
    assert paths.trace_jsonl == paths.output_dir / "trace.jsonl"


def test_mint_run_paths_mints_ids_when_omitted(tmp_path: Path) -> None:
    paths = mint_run_paths(tmp_path)
    assert paths.run_id  # non-empty
    assert paths.session_id == paths.run_id  # default ties them
    assert paths.output_dir.name == paths.run_id


def test_cli_dry_run_does_not_call_sdk(tmp_path: Path) -> None:
    """`--dry-run --skip-doctor` should print a plan and exit 0."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "proteinclaw.cli",
            "run",
            "design a tiny binder",
            "--dry-run",
            "--skip-doctor",
            "--output-dir",
            str(tmp_path / "runs"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DRY RUN" in proc.stdout
    assert "tools exposed" in proc.stdout
    assert "design a tiny binder" in proc.stdout


def test_cli_refuses_without_doctor_ok(monkeypatch, tmp_path: Path) -> None:
    """If doctor_ok() returns False and --skip-doctor not passed, exit 1."""
    # Point the marker at a path that doesn't exist; cli imports doctor_ok
    # at module load so we need to do it via env or subprocess.
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; "
            "os.environ['HOME'] = '" + str(tmp_path) + "'; "
            "from proteinclaw.cli import app; "
            "sys.argv = ['proteinclaw', 'run', 'x', '--output-dir', '" + str(tmp_path) + "']; "
            "app()",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "doctor" in (proc.stderr + proc.stdout).lower()


def test_trace_tailer_streams_codex_mcp_events(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({"type": "run_started", "run_id": "r"}) + "\n",
        encoding="utf-8",
    )
    chunks: list[tuple[str, str]] = []

    async def _run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(_tail_trace_for_stream(trace, lambda k, p: chunks.append((k, p)), stop))
        await asyncio.sleep(0.05)
        with trace.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "tool_use",
                "tool_use_id": "codex-mcp-1",
                "name": "skills_list",
                "input": {},
            }) + "\n")
            f.write(json.dumps({
                "type": "tool_result",
                "tool_use_id": "codex-mcp-1",
                "is_error": False,
                "content": "{\"summary\":\"ok\"}",
            }) + "\n")
        await asyncio.sleep(0.35)
        stop.set()
        await task

    asyncio.run(_run())

    assert chunks == [
        ("tool_use", "skills_list({})"),
        ("tool_result", "{\"summary\":\"ok\"}"),
    ]

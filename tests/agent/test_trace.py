"""TraceWriter — JSONL append + typed helpers + long-string trimming."""

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.agent.trace import TraceWriter


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_run_lifecycle(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    with TraceWriter(p) as t:
        t.run_started(
            run_id="r1",
            session_id="s1",
            prompt="hi",
            output_dir=str(tmp_path),
            model="claude-opus-4-7",
            skill_chars=42,
        )
        t.assistant_text("Hello")
        t.tool_use(tool_use_id="u1", name="mcp__proteinclaw_tools__data_pdb_fetch", input={"pdb_id": "5JDS"})
        t.tool_result(
            tool_use_id="u1",
            is_error=False,
            content=[{"type": "text", "text": '{"summary":"ok"}'}],
        )
        t.run_completed(
            session_id="s1",
            num_turns=4,
            total_cost_usd=0.123,
            duration_ms=1234,
            elapsed_wall_s=1.5,
        )

    rows = _lines(p)
    types = [r["type"] for r in rows]
    assert types == [
        "run_started",
        "assistant_text",
        "tool_use",
        "tool_result",
        "run_completed",
    ]
    assert all("ts" in r for r in rows)
    assert rows[0]["run_id"] == "r1"
    assert rows[1]["text"] == "Hello"
    assert rows[2]["name"].endswith("data_pdb_fetch")
    assert rows[3]["is_error"] is False


def test_long_string_trimmed(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    big = "X" * 10_000
    with TraceWriter(p) as t:
        t.tool_result(tool_use_id="u1", is_error=False, content=big)
    rows = _lines(p)
    assert "[truncated" in rows[0]["content"]


def test_failure_event_recorded(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    with TraceWriter(p) as t:
        t.run_failed(error="boom", exception_type="RuntimeError")
    rows = _lines(p)
    assert rows[0]["type"] == "run_failed"
    assert rows[0]["exception_type"] == "RuntimeError"

"""Run-activity timeline: _collect_activity (trace → structured events) +
_render_activity (events → report HTML section)."""

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.agent.core import (
    _collect_activity,
    _collect_trace_events,
    _read_plan_md,
    _TRACE_FIELD_CAP,
)
from proteinclaw.agent.skills import _SKILLS_DIR
from proteinclaw.report import _render_activity


def _write_trace(tmp_path: Path) -> Path:
    skill_file = str(_SKILLS_DIR / "learned" / "demo.md")  # under the skills dir
    events = [
        {"type": "run_started"},
        {"type": "subagent_spawn", "subagent_type": "research", "description": "TREM2 surface"},
        {"type": "subagent_spawn", "subagent_type": "research", "description": "Challenge: epitope"},
        {
            "type": "tool_use",
            "name": "mcp__proteinclaw_tools__design_rfdiffusion3",
            "input": {"hotspot_residues": "A23,A107", "binder_length": "70-90", "num_designs": 8},
        },
        {"type": "tool_use", "name": "Write", "input": {"file_path": skill_file}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},  # ignored
        {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/run/plan.md"}},  # not a skill
        {"type": "assistant_text", "text": "narration — ignored by activity"},
    ]
    p = tmp_path / "trace.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def test_collect_activity_extracts_debate_pipeline_skill(tmp_path: Path) -> None:
    acts = _collect_activity(_write_trace(tmp_path))
    kinds = [a["kind"] for a in acts]
    assert kinds == ["debate", "debate", "pipeline", "skill"]  # Bash + plan.md + text excluded
    assert "Challenge: epitope" in acts[1]["label"]
    assert "RFdiffusion3" in acts[2]["label"] and "A23,A107" in acts[2]["label"]
    assert acts[3]["label"] == "skill created: learned/demo.md"


def test_collect_activity_missing_trace(tmp_path: Path) -> None:
    assert _collect_activity(tmp_path / "nope.jsonl") == []


def test_render_activity_includes_evolved_block_and_timeline() -> None:
    html = _render_activity(
        [
            {"kind": "debate", "label": "research: surface"},
            {"kind": "pipeline", "label": "RFdiffusion3 — n=8"},
            {"kind": "skill", "label": "skill created: learned/x.md"},
        ],
        skill_edits=["/abs/skills/learned/x.md"],
    )
    assert "Run activity" in html
    assert "Skills evolved this run" in html
    for cls in ("act-debate", "act-pipeline", "act-skill"):
        assert cls in html


def test_render_activity_empty() -> None:
    html = _render_activity([], skill_edits=[])
    assert "No structured activity captured" in html
    assert "Skills evolved this run" not in html


def test_collect_trace_events_parses_and_caps(tmp_path: Path) -> None:
    big = "x" * (_TRACE_FIELD_CAP + 500)
    p = tmp_path / "trace.jsonl"
    p.write_text(
        json.dumps({"type": "run_started"}) + "\n"
        + "not json\n"  # malformed line is skipped
        + json.dumps({"type": "assistant_text", "text": big}) + "\n"
    )
    events = _collect_trace_events(p)
    assert [e["type"] for e in events] == ["run_started", "assistant_text"]
    # Over-long string field is truncated with a marker.
    assert len(events[1]["text"]) < len(big)
    assert "chars)" in events[1]["text"]


def test_collect_trace_events_missing(tmp_path: Path) -> None:
    assert _collect_trace_events(tmp_path / "nope.jsonl") == []


def test_read_plan_md(tmp_path: Path) -> None:
    p = tmp_path / "plan.md"
    p.write_text("# Run plan\n## Debate\n- converged")
    assert "Debate" in _read_plan_md(p)
    assert _read_plan_md(tmp_path / "absent.md") == ""

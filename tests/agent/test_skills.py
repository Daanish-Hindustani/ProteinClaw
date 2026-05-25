"""Skill loader — fail loud on missing/empty, return content otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.agent.skills import SkillLoadError, load_skill_text


def test_loads_bundled_skill() -> None:
    text = load_skill_text()
    # Just sanity-check the file is non-trivial and mentions a few markers.
    assert len(text) > 500
    assert "proteinclaw" in text.lower()
    assert "mcp__proteinclaw_tools__" in text
    # The appended tool skill index is part of what callers get.
    assert "Tool skill index" in text


def test_bundled_tool_skill_files_exist_and_nontrivial() -> None:
    from proteinclaw.agent.skills import _SKILL_PATH

    tool_dir = _SKILL_PATH.parent / "tools"
    expected = {"rfdiffusion3.md", "proteinmpnn.md", "esmfold.md", "alphafold2_multimer.md"}
    present = {f.name for f in tool_dir.glob("*.md")}
    assert expected <= present, f"missing tool skill files: {expected - present}"
    for f in tool_dir.glob("*.md"):
        assert len(f.read_text(encoding="utf-8").strip()) > 200, f"{f.name} too short"


def test_missing_tool_skills_dir_raises(tmp_path: Path) -> None:
    """A valid core file with no tools/ dir next to it must fail loud — the
    step 4–7 pointers would otherwise dangle."""
    core = tmp_path / "proteindesign.md"
    core.write_text("# core skill\n\nmcp__proteinclaw_tools__design_rfdiffusion3\n")
    with pytest.raises(SkillLoadError, match="per-tool skill"):
        load_skill_text(core)


def test_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(SkillLoadError, match="not found"):
        load_skill_text(tmp_path / "no_such.md")


def test_empty_file_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.md"
    empty.write_text("")
    with pytest.raises(SkillLoadError, match="empty"):
        load_skill_text(empty)


def test_whitespace_only_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws.md"
    ws.write_text("\n\n   \t\n")
    with pytest.raises(SkillLoadError, match="empty"):
        load_skill_text(ws)

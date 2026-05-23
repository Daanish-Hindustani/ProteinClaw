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

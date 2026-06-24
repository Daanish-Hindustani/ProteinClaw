"""Hermes skill seeding/snapshot + skill_manage edit extraction."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.agent.core import _skill_edits_from_calls
from proteinclaw.agent.skills import (
    ensure_hermes_skills,
    load_skill_text,
    reset_hermes_skills,
    snapshot_hermes_skills,
)


def _seed_core_and_tools(tmp_path: Path) -> Path:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "rfdiffusion3.md").write_text("# rfd3\n" * 40)
    core = tmp_path / "proteindesign.md"
    core.write_text("# core\nmcp__proteinclaw_tools__design_rfdiffusion3\n")
    return core


def test_load_skill_indexes_learned_dir(tmp_path: Path) -> None:
    core = _seed_core_and_tools(tmp_path)
    (tmp_path / "learned").mkdir()
    learned = tmp_path / "learned" / "igv-fold.md"
    learned.write_text("# IgV fold playbook\n" * 10)

    text = load_skill_text(core)
    assert "Learned skills" in text
    assert "learned/igv-fold.md" in text
    assert learned.as_posix() in text
    assert "Hermes Skill Evolution" in text
    assert "skill_manage" in text


def test_load_skill_tolerates_absent_learned_dir(tmp_path: Path) -> None:
    core = _seed_core_and_tools(tmp_path)
    text = load_skill_text(core)
    assert "Tool skill index" in text
    assert "Learned skills" not in text


def test_skill_edits_from_calls_filters_skill_manage() -> None:
    calls = [
        {"name": "skill_manage", "input": {"skill": "proteinclaw-tool-esmfold"}},
        {"name": "skill_manage", "input": {"skill_name": "proteinclaw-minibinder"}},
        {"name": "file_write", "input": {"path": "/tmp/run/plan.md"}},
    ]
    edits = _skill_edits_from_calls(calls)
    assert edits == ["proteinclaw-minibinder", "proteinclaw-tool-esmfold"]


def test_hermes_skill_seed_snapshot_reset(tmp_path: Path) -> None:
    source = tmp_path / "srcskills"
    source.mkdir()
    (source / "proteindesign.md").write_text("# mini\n")
    (source / "nanobody.md").write_text("# nano\n")
    (source / "tools").mkdir()
    (source / "tools" / "esmfold.md").write_text("# esm\n")
    root = tmp_path / "active"

    ensure_hermes_skills(source_dir=source, root=root)
    mini = root / "proteinclaw-minibinder" / "SKILL.md"
    assert mini.exists()
    assert mini.read_text().startswith("---\nname: proteinclaw-minibinder")
    assert (root / "proteinclaw-tool-esmfold" / "SKILL.md").exists()

    mini.write_text(mini.read_text() + "\n## Learned (run abc): x\n")
    snap = snapshot_hermes_skills(tmp_path / "run", root=root)
    assert (snap / "proteinclaw-minibinder" / "SKILL.md").exists()

    reset_hermes_skills(source_dir=source, root=root)
    assert "Learned (run abc)" not in mini.read_text()

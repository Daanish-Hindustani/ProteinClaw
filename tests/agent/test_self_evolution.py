"""Self-evolution: learned/ skill indexing + skill-edit extraction."""

from __future__ import annotations

from pathlib import Path

from proteinclaw.agent.core import _skill_edits_from_calls
from proteinclaw.agent.skills import _SKILLS_DIR, load_skill_text


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
    assert "Learned skills" in text                 # learned subsection rendered
    assert "learned/igv-fold.md" in text            # relative ref
    assert str(learned) in text                     # absolute path for on-demand Read


def test_load_skill_tolerates_absent_learned_dir(tmp_path: Path) -> None:
    core = _seed_core_and_tools(tmp_path)            # no learned/ dir created
    text = load_skill_text(core)
    assert "Tool skill index" in text               # tools index still present
    assert "Learned skills" not in text             # no learned section when empty


def test_skill_edits_from_calls_filters_skill_writes() -> None:
    skill_file = str(_SKILLS_DIR / "tools" / "esmfold.md")
    new_learned = str(_SKILLS_DIR / "learned" / "new-topic.md")
    calls = [
        {"name": "Write", "input": {"file_path": skill_file}},
        {"name": "Edit", "input": {"file_path": new_learned}},
        {"name": "Write", "input": {"file_path": "/tmp/run/plan.md"}},   # run-local, not a skill
        {"name": "Read", "input": {"file_path": skill_file}},            # read, not an edit
        {"name": "Bash", "input": {"command": "ls"}},                    # no file_path
    ]
    edits = _skill_edits_from_calls(calls)
    assert skill_file in edits
    assert new_learned in edits
    assert "/tmp/run/plan.md" not in edits
    assert len(edits) == 2


def test_skill_edits_dedupes_and_sorts() -> None:
    f = str(_SKILLS_DIR / "tools" / "proteinmpnn.md")
    edits = _skill_edits_from_calls(
        [{"name": "Edit", "input": {"file_path": f}}, {"name": "Edit", "input": {"file_path": f}}]
    )
    assert edits == [f]

"""Tests for skills/skill.py — model invariants, front-matter parsing, file loading."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from proteinclaw.skills.skill import (
    Skill,
    SkillParseError,
    SkillProvenance,
    load_skill_file,
    parse_markdown_skill,
)


def _valid_markdown(version: int = 1, parent: int | None = None) -> str:
    parent_yaml = "null" if parent is None else str(parent)
    return dedent(
        f"""\
        ---
        id: test_skill
        version: {version}
        name: Test Skill
        description: A test skill.
        applicable_tasks: [test_task]
        provenance: human_authored
        parent_version: {parent_yaml}
        ---

        Body content here.
        """
    )


def test_parse_minimal_skill() -> None:
    skill = parse_markdown_skill(_valid_markdown())
    assert skill.id == "test_skill"
    assert skill.version == 1
    assert skill.provenance == SkillProvenance.HUMAN_AUTHORED
    assert skill.applicable_tasks == ("test_task",)
    assert "Body content here." in skill.body


def test_skill_is_frozen() -> None:
    skill = parse_markdown_skill(_valid_markdown())
    with pytest.raises(ValidationError):
        skill.version = 99  # type: ignore[misc]


def test_version_id_property() -> None:
    skill = parse_markdown_skill(_valid_markdown(version=3))
    assert skill.version_id == "test_skill@v3"


def test_missing_front_matter_rejected() -> None:
    with pytest.raises(SkillParseError):
        parse_markdown_skill("just text, no front matter")


def test_unclosed_front_matter_rejected() -> None:
    with pytest.raises(SkillParseError):
        parse_markdown_skill("---\nid: x\nversion: 1")


def test_invalid_yaml_rejected() -> None:
    bad = "---\nid: [unclosed\n---\nbody\n"
    with pytest.raises(SkillParseError):
        parse_markdown_skill(bad)


def test_non_mapping_front_matter_rejected() -> None:
    bad = "---\n- a list\n- not a mapping\n---\nbody\n"
    with pytest.raises(SkillParseError):
        parse_markdown_skill(bad)


def test_invalid_schema_rejected() -> None:
    bad = dedent(
        """\
        ---
        id: x
        version: 0
        name: bad
        description: zero version
        provenance: human_authored
        ---

        body
        """
    )
    with pytest.raises(SkillParseError):
        parse_markdown_skill(bad)


def test_round_trip_via_pydantic() -> None:
    skill = parse_markdown_skill(_valid_markdown())
    rt = Skill.model_validate_json(skill.model_dump_json())
    assert rt == skill


def test_load_skill_file(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text(_valid_markdown())
    assert load_skill_file(f).id == "test_skill"

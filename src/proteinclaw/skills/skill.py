"""Skill model and Markdown front-matter loader.

Skills are *data*, not code. They live as Markdown files with a YAML
front-matter block describing the skill's identity and applicability:

```markdown
---
id: binder_design
name: Binder Design
version: 1
applicable_tasks: [binder_design]
provenance: human_authored
parent_version: null
---

Step 1: Retrieve the target structure with the rcsb tool...
```

The Evolution Service rewrites skills via patch-or-rewrite (Phase 7); each
edit increments `version` and links back through `parent_version`, so the
Trace Store can show the lineage of every active skill.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SkillProvenance(StrEnum):
    """Where a skill came from. Required so the registry can audit edits."""

    HUMAN_AUTHORED = "human_authored"
    EVOLVED = "evolved"


class SkillExample(BaseModel):
    """One worked example of a skill's input/output, to ground LLM selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]


class Skill(BaseModel):
    """One skill in the library.

    Attributes:
        id: Stable identifier shared across versions (e.g. ``binder_design``).
        version: Monotonically increasing per id; 1 for the first version.
        name: Human-readable label.
        description: Short summary surfaced to the planner.
        applicable_tasks: Task tags this skill applies to. Used by
            `SkillLibrary.find_for(task_type)`.
        body: Markdown body with the workflow steps.
        provenance: Whether this version was authored by a human or evolved.
        parent_version: Previous version id was patched from, or None for
            initial human-authored versions.
        examples: Optional worked examples.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int = Field(ge=1)
    name: str
    description: str
    applicable_tasks: tuple[str, ...] = ()
    body: str
    provenance: SkillProvenance
    parent_version: int | None = None
    examples: tuple[SkillExample, ...] = ()

    @property
    def version_id(self) -> str:
        """Composite identifier suitable for `BranchResult.skill_version_id`."""
        return f"{self.id}@v{self.version}"


class SkillParseError(ValueError):
    """Raised when a Markdown skill file cannot be parsed.

    Distinct from validation errors — this fires when the file is
    structurally malformed (missing front-matter, invalid YAML, etc.).
    """


_FRONT_MATTER_DELIMITER = "---"


def parse_markdown_skill(text: str) -> Skill:
    """Parse a Markdown skill (front-matter + body) into a `Skill`.

    Args:
        text: Full file contents, starting with ``---``.

    Returns:
        A validated `Skill` instance.

    Raises:
        SkillParseError: When the front-matter block is missing,
            malformed, or the resulting fields fail Pydantic validation.
    """
    if not text.lstrip().startswith(_FRONT_MATTER_DELIMITER):
        raise SkillParseError("missing YAML front-matter delimiter")

    # Split on the first two `---` lines.
    stripped = text.lstrip()
    after_first = stripped[len(_FRONT_MATTER_DELIMITER) :].lstrip("\n")
    end = after_first.find(f"\n{_FRONT_MATTER_DELIMITER}")
    if end == -1:
        raise SkillParseError("front-matter not closed by `---`")
    front_raw = after_first[:end]
    body = after_first[end + len(_FRONT_MATTER_DELIMITER) + 1 :].lstrip("\n")

    try:
        front: dict[str, Any] = yaml.safe_load(front_raw) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"invalid YAML front-matter: {e}") from e
    if not isinstance(front, dict):
        raise SkillParseError("front-matter must be a YAML mapping")

    payload = {**front, "body": body}
    try:
        return Skill.model_validate(payload)
    except Exception as e:
        raise SkillParseError(f"skill validation failed: {e}") from e


def load_skill_file(path: Path) -> Skill:
    """Read and parse a Markdown skill file from disk.

    Args:
        path: Path to a ``.md`` file with valid front-matter.

    Returns:
        A validated `Skill` instance.
    """
    return parse_markdown_skill(path.read_text(encoding="utf-8"))

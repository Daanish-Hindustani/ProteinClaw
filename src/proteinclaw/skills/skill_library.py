"""SkillLibrary: in-memory store of validated skills, indexed by id and version.

Every skill that lands in the library has been through `SkillValidator`.
The library tracks all versions of each skill — the Evolution Service in
Phase 7 will add new versions; the library serves the latest by default
but can serve any historical version for audit and rollback.

Phase 5 will back this with SQLite. Phase 1+ tests can construct a
library in-process via `from_directory()`.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from proteinclaw.skills.skill import Skill, load_skill_file
from proteinclaw.skills.skill_validator import SkillValidator


class DuplicateSkillVersionError(ValueError):
    """Raised when a skill (id, version) pair is added twice."""


class UnknownSkillError(KeyError):
    """Raised when looking up a skill id (or specific version) that is not registered."""


class SkillLibrary:
    """Versioned skill store with retrieval by id, version, and task type.

    Skills are keyed by `(id, version)`. The library exposes the latest
    version by default; historical versions remain reachable for audit.
    """

    def __init__(self, validator: SkillValidator | None = None) -> None:
        """Initialize an empty library.

        Args:
            validator: Optional validator. When None, a default
                `SkillValidator` is constructed — every `add()` call goes
                through it. Pass an alternative for tests.
        """
        self._validator = validator or SkillValidator()
        # Outer key: skill id. Inner key: version → Skill.
        self._by_id: dict[str, dict[int, Skill]] = {}

    def add(self, skill: Skill) -> None:
        """Validate and register `skill`.

        Raises:
            SkillValidationError: From the validator on threat/structural issues.
            DuplicateSkillVersionError: If `(skill.id, skill.version)` is
                already registered. Re-adding the same version would silently
                overwrite — explicit failure is safer.
        """
        self._validator.validate(skill)
        versions = self._by_id.setdefault(skill.id, {})
        if skill.version in versions:
            raise DuplicateSkillVersionError(
                f"{skill.id} version {skill.version} already registered"
            )
        versions[skill.version] = skill

    def get(self, skill_id: str, version: int) -> Skill:
        """Return a specific `(skill_id, version)`. Raises if missing."""
        versions = self._by_id.get(skill_id)
        if versions is None or version not in versions:
            raise UnknownSkillError(f"{skill_id}@v{version}")
        return versions[version]

    def latest(self, skill_id: str) -> Skill:
        """Return the latest registered version of `skill_id`."""
        versions = self._by_id.get(skill_id)
        if not versions:
            raise UnknownSkillError(skill_id)
        return versions[max(versions)]

    def all_latest(self) -> list[Skill]:
        """Return every skill at its latest version, sorted by id."""
        return [self.latest(sid) for sid in sorted(self._by_id)]

    def find_for(self, task_type: str) -> list[Skill]:
        """Return latest versions whose `applicable_tasks` includes `task_type`.

        Sorted by skill id. The ranking will get smarter in Phase 4 when
        sub-agents pick a skill via the LLM; for Phase 3 keyword/tag
        matching is enough.
        """
        return [s for s in self.all_latest() if task_type in s.applicable_tasks]

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        validator: SkillValidator | None = None,
    ) -> SkillLibrary:
        """Construct a library from every `.md` file under `directory`.

        Files that fail to parse or validate raise — partial loads are
        not allowed. This keeps the live library in a known-good state.
        """
        lib = cls(validator=validator)
        for skill in _iter_skills(directory):
            lib.add(skill)
        return lib


def _iter_skills(directory: Path) -> Iterable[Skill]:
    """Yield every Skill loaded from `*.md` files under `directory`."""
    for path in sorted(directory.rglob("*.md")):
        yield load_skill_file(path)

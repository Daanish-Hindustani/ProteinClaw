"""SkillValidator: schema check + prompt-injection threat scan.

Both human-authored and agent-authored skills must pass the validator
before entering the library. Schema validation is handled by Pydantic when
the Skill is constructed; this module adds a content-level scan for
prompt-injection patterns the Evolution Service might be tricked into
producing.

The threat scan is heuristic, not exhaustive. The goal is to catch the
obvious cases ("ignore previous instructions", embedded `<system>` tags,
role-redefinition attempts) and fail loudly so a human can review. Phase 7
will tighten this when real evolution kicks in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from proteinclaw.skills.skill import Skill

# Patterns that strongly suggest prompt injection. Flagged eagerly — false
# positives are cheaper than false negatives at this stage.
_THREAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|context)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard",
        re.compile(r"\bdisregard\s+(any|all|the)\s+(prior|above|previous)\b", re.IGNORECASE),
    ),
    (
        "system_role_redefinition",
        re.compile(
            r"\b(you\s+are\s+now|you\s+must\s+now)\b.*\b(act|pretend|behave)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_tag",
        re.compile(r"<\s*(system|admin|sudo|root)\s*>", re.IGNORECASE),
    ),
    (
        "raw_credentials",
        re.compile(r"\b(api[_-]?key|password|secret|token)\s*[:=]\s*\S{8,}", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class ValidationIssue:
    """One issue surfaced by the validator."""

    code: str
    message: str


class SkillValidationError(ValueError):
    """Raised when validation finds at least one blocking issue.

    Carries the full list so the caller can surface them all at once.

    Attributes:
        skill_id: Identifier of the rejected skill.
        issues: All issues found (≥ 1; if zero issues, this exception
            should not have been raised).
    """

    def __init__(self, skill_id: str, issues: tuple[ValidationIssue, ...]) -> None:
        """Construct a validation error attached to `skill_id` with `issues`."""
        if not issues:
            raise ValueError("SkillValidationError requires ≥ 1 issue")
        self.skill_id = skill_id
        self.issues = issues
        joined = "; ".join(f"[{i.code}] {i.message}" for i in issues)
        super().__init__(f"skill {skill_id!r}: {joined}")


class SkillValidator:
    """Schema + threat-scan gate for the Skill Library.

    Stateless. Construct once; call `validate(skill)` per skill before
    persistence.
    """

    def validate(self, skill: Skill) -> None:
        """Validate `skill`. Raises on any issue, returns None on success.

        Args:
            skill: A constructed `Skill` (Pydantic schema already applied).

        Raises:
            SkillValidationError: If any threat pattern matches the body
                or other content-level checks fail.
        """
        issues: list[ValidationIssue] = []
        issues.extend(self._scan_threats(skill))
        issues.extend(self._scan_structural(skill))
        if issues:
            raise SkillValidationError(skill.id, tuple(issues))

    def _scan_threats(self, skill: Skill) -> list[ValidationIssue]:
        """Run regex threat patterns against the body."""
        out: list[ValidationIssue] = []
        for code, pattern in _THREAT_PATTERNS:
            match = pattern.search(skill.body)
            if match:
                out.append(
                    ValidationIssue(
                        code=f"threat.{code}",
                        message=f"matched suspicious pattern: {match.group(0)!r}",
                    )
                )
        return out

    def _scan_structural(self, skill: Skill) -> list[ValidationIssue]:
        """Cheap structural checks beyond the schema."""
        out: list[ValidationIssue] = []
        if not skill.body.strip():
            out.append(ValidationIssue("structure.empty_body", "skill body is empty"))
        if skill.parent_version is not None and skill.parent_version >= skill.version:
            out.append(
                ValidationIssue(
                    "structure.bad_lineage",
                    f"parent_version {skill.parent_version} must be < version {skill.version}",
                )
            )
        if skill.provenance is None:  # pragma: no cover — schema enforces, defensive only
            out.append(ValidationIssue("structure.no_provenance", "provenance missing"))
        return out

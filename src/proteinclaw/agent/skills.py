"""Eager loader for the ``proteindesign.md`` skill file (PRD §6.3).

The skill file is **not** lazy-loaded. It is read once at agent init and
appended to the SDK's default Claude Code system prompt. Editing the
file is the supported way to change agent behavior without a code change.
"""

from __future__ import annotations

from pathlib import Path

_SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "proteindesign.md"


class SkillLoadError(RuntimeError):
    """Raised when the skill file is missing — loud failure on purpose."""


def load_skill_text(path: Path = _SKILL_PATH) -> str:
    """Return the skill file contents. Raises if the file is missing.

    Note: callers are expected to surface the raised error rather than
    swallow it. A missing skill file silently degrades the agent's
    behavior, which is exactly the kind of "honesty about implementation
    state" failure CLAUDE.md flags.
    """
    if not path.exists():
        raise SkillLoadError(
            f"skill file not found at {path}; agent cannot run without it"
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SkillLoadError(
            f"skill file at {path} is empty; agent cannot run without it"
        )
    return text


__all__ = ["SkillLoadError", "load_skill_text"]

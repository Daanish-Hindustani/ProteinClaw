"""Loader for the ``proteindesign.md`` skill file (PRD §6.3).

The **core** skill file is read once at agent init and appended to the
SDK's default Claude Code system prompt. Editing it is the supported
way to change agent behavior without a code change.

Per-tool operational detail lives in ``skills/tools/<tool>.md`` and is
**progressively disclosed**: the core skill only summarises pipeline
steps 4–7, and the agent ``Read``s the relevant tool skill file on
demand before each step. To make those ``Read``s resolve regardless of
the agent's working directory, ``load_skill_text`` appends a **Tool
skill index** mapping each ``tools/<name>.md`` reference to its absolute
path. Both the core file and at least one tool file must exist — a
missing skill silently degrades the agent, which CLAUDE.md flags as an
honesty failure, so we fail loud.
"""

from __future__ import annotations

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILL_PATH = _SKILLS_DIR / "proteindesign.md"


class SkillLoadError(RuntimeError):
    """Raised when a skill file is missing/empty — loud failure on purpose."""


def _tool_skill_index(tool_dir: Path) -> str:
    """Render the absolute-path index of per-tool skill files.

    Raises if the directory is missing or empty: the core skill's step
    4–7 summaries are useless without the tool files they point to.
    """
    files = sorted(tool_dir.glob("*.md")) if tool_dir.is_dir() else []
    if not files:
        raise SkillLoadError(
            f"no per-tool skill files found in {tool_dir}; the core skill's "
            "progressive-disclosure pointers (steps 4–7) cannot resolve"
        )
    lines = [
        "",
        "---",
        "",
        "## Tool skill index (`Read` the file before each tool step)",
        "",
        "The step 4–7 summaries above are deliberately brief. Before you call",
        "each tool in a round, `Read` its skill file at the **absolute path**",
        "below — your cwd is the run dir, so use these paths, not the relative",
        "`tools/<name>.md` form:",
        "",
    ]
    lines += [f"- `tools/{f.name}` → `{f}`" for f in files]
    lines.append("")
    return "\n".join(lines)


def load_skill_text(path: Path = _SKILL_PATH) -> str:
    """Return the core skill text + the appended tool skill index.

    Raises ``SkillLoadError`` if the core file is missing/empty or if no
    per-tool skill files exist next to it (in ``<path.parent>/tools``).
    Callers should surface the error rather than swallow it.
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
    return text + _tool_skill_index(path.parent / "tools")


__all__ = ["SkillLoadError", "load_skill_text"]

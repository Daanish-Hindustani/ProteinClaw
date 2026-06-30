"""Loader and plugin-skill helpers for ProteinClaw workflow skills."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLUGIN_SKILLS_DIR = _REPO_ROOT / "skills"
_SKILLS_DIR = _PLUGIN_SKILLS_DIR
_SKILL_PATH = _PLUGIN_SKILLS_DIR / "proteinclaw-minibinder" / "SKILL.md"
_WORKFLOW_SKILLS = {
    "minibinder": _SKILL_PATH,
    "nanobody": _PLUGIN_SKILLS_DIR / "proteinclaw-nanobody" / "SKILL.md",
}


class SkillLoadError(RuntimeError):
    """Raised when a skill file is missing/empty."""


def skill_path_for_workflow(workflow: str) -> Path:
    """Resolve the plugin skill file for a workflow selection."""
    return _WORKFLOW_SKILLS.get(workflow, _SKILL_PATH)


def plugin_skills_root(root: Path | None = None) -> Path:
    """Return the canonical plugin skill root.

    The repository uses top-level ``skills/`` for plugin packaging. Tests and
    local installs can override it with ``PROTEINCLAW_SKILLS_DIR``.
    """
    if root is not None:
        return Path(root).expanduser().resolve()
    env = os.environ.get("PROTEINCLAW_SKILLS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _PLUGIN_SKILLS_DIR.resolve()


def ensure_plugin_skills(*, root: Path | None = None) -> Path:
    """Return the plugin skill root, creating it if an override points nowhere."""
    root_path = plugin_skills_root(root)
    root_path.mkdir(parents=True, exist_ok=True)
    return root_path


def _skill_files(prefix: str, root: Path) -> list[Path]:
    return sorted(root.glob(f"{prefix}*/SKILL.md"))


def _tool_skill_index(skills_dir: Path) -> str:
    """Render the absolute-path index of per-tool + learned plugin skill files."""
    root = skills_dir.parent if skills_dir.name != "skills" else skills_dir
    tool_files = _skill_files("proteinclaw-tool-", root)
    if not tool_files:
        raise SkillLoadError(
            f"no per-tool skill files found in {root}; the core skill's "
            "progressive-disclosure pointers cannot resolve"
        )
    learned_files = _skill_files("proteinclaw-learned-", root)

    lines = [
        "",
        "---",
        "",
        "## Tool skill index (`Read` the file before each tool step)",
        "",
        "Before each GPU/scoring step, read the relevant plugin skill file:",
        "",
    ]
    lines += [f"- `{f.parent.name}` -> `{f.as_posix()}`" for f in tool_files]
    if learned_files:
        lines += [
            "",
            "**Learned skills** - cross-run lessons recorded in plugin skills:",
            "",
        ]
        lines += [f"- `{f.parent.name}` -> `{f.as_posix()}`" for f in learned_files]
    lines.append("")
    return "\n".join(lines)


_PLUGIN_SKILL_GUIDANCE = """

---

## Plugin Skill Evolution

ProteinClaw's canonical agent-facing skills live in the plugin `skills/`
directory. Use the ProteinClaw MCP skill tools for durable procedural memory:
`proteinclaw_skill_read`, `proteinclaw_skill_write`, `proteinclaw_skill_patch`,
`proteinclaw_skill_create`, and `proteinclaw_skill_delete`. Prefer clean,
frontmatter-valid skills over append-only logs: create focused learned skills,
patch or rewrite existing skills when guidance changes, and delete obsolete
ProteinClaw skills when they would mislead future runs. Run-local files remain
under the run directory.
"""


def load_skill_text(path: Path = _SKILL_PATH) -> str:
    """Return the plugin skill text plus the tool/learned index."""
    if not path.exists():
        raise SkillLoadError(f"skill file not found at {path}; agent cannot run without it")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SkillLoadError(f"skill file at {path} is empty; agent cannot run without it")
    return text + _tool_skill_index(path.parent) + _PLUGIN_SKILL_GUIDANCE


__all__ = [
    "SkillLoadError",
    "ensure_plugin_skills",
    "load_skill_text",
    "plugin_skills_root",
    "skill_path_for_workflow",
]

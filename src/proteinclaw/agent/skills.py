"""Loader and Hermes skill-store helpers for ProteinClaw workflow skills."""

from __future__ import annotations

import difflib
import os
import shutil
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILL_PATH = _SKILLS_DIR / "proteindesign.md"
_WORKFLOW_SKILLS = {
    "minibinder": _SKILL_PATH,
    "nanobody": _SKILLS_DIR / "nanobody.md",
}
_HERMES_SKILL_NAMES = {
    "proteindesign.md": "proteinclaw-minibinder",
    "nanobody.md": "proteinclaw-nanobody",
}


class SkillLoadError(RuntimeError):
    """Raised when a skill file is missing/empty — loud failure on purpose."""


def skill_path_for_workflow(workflow: str) -> Path:
    """Resolve the core skill file for a `--workflow` selection."""
    return _WORKFLOW_SKILLS.get(workflow, _SKILL_PATH)


def _tool_skill_index(skills_dir: Path) -> str:
    """Render the absolute-path index of per-tool + learned skill files."""
    tool_dir = skills_dir / "tools"
    tool_files = sorted(tool_dir.glob("*.md")) if tool_dir.is_dir() else []
    if not tool_files:
        raise SkillLoadError(
            f"no per-tool skill files found in {tool_dir}; the core skill's "
            "progressive-disclosure pointers (steps 4-7) cannot resolve"
        )
    learned_dir = skills_dir / "learned"
    learned_files = sorted(learned_dir.glob("*.md")) if learned_dir.is_dir() else []

    lines = [
        "",
        "---",
        "",
        "## Tool skill index (`Read` the file before each tool step)",
        "",
        "The step 4-7 summaries above are deliberately brief. Before you call",
        "each tool in a round, `Read` its skill file at the **absolute path**",
        "below — your cwd is the run dir, so use these paths, not the relative",
        "`tools/<name>.md` form:",
        "",
    ]
    lines += [f"- `tools/{f.name}` → `{f.as_posix()}`" for f in tool_files]
    if learned_files:
        lines += [
            "",
            "**Learned skills** — cross-run lessons recorded by self-evolution",
            "(see the core skill's Self-evolution section). `Read` any that",
            "match the current target / fold class / tool:",
            "",
        ]
        lines += [f"- `learned/{f.name}` → `{f.as_posix()}`" for f in learned_files]
    lines.append("")
    return "\n".join(lines)


def hermes_skills_root(root: Path | None = None) -> Path:
    """Return ProteinClaw's Hermes skills storage root."""
    if root is not None:
        return Path(root).expanduser().resolve()
    env = os.environ.get("PROTEINCLAW_HERMES_SKILLS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    try:
        from hermes_constants import get_skills_dir  # type: ignore

        return (get_skills_dir() / "proteinclaw").expanduser().resolve()
    except Exception:  # noqa: BLE001 - fallback for dry-run/test envs without Hermes
        return (Path.home() / ".hermes" / "skills" / "proteinclaw").resolve()


def _skill_frontmatter(name: str, source: Path) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: ProteinClaw workflow and tool guidance seeded from the repository.\n"
        f"source: {source}\n"
        "---\n\n"
    )


def _write_seed_skill(source: Path, dest: Path, name: str, *, overwrite: bool = False) -> None:
    if dest.exists() and not overwrite:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = source.read_text(encoding="utf-8")
    dest.write_text(_skill_frontmatter(name, source) + body, encoding="utf-8")


def ensure_hermes_skills(*, source_dir: Path | None = None, root: Path | None = None) -> Path:
    """Seed ProteinClaw skills into Hermes storage if they do not exist."""
    source_dir = source_dir or _SKILLS_DIR
    root_path = hermes_skills_root(root)
    for filename, name in _HERMES_SKILL_NAMES.items():
        source = source_dir / filename
        if source.exists():
            _write_seed_skill(source, root_path / name / "SKILL.md", name)
    tools_dir = source_dir / "tools"
    if tools_dir.is_dir():
        for source in sorted(tools_dir.glob("*.md")):
            name = f"proteinclaw-tool-{source.stem.replace('_', '-')}"
            _write_seed_skill(source, root_path / name / "SKILL.md", name)
    learned_dir = source_dir / "learned"
    if learned_dir.is_dir():
        for source in sorted(learned_dir.glob("*.md")):
            name = f"proteinclaw-learned-{source.stem.replace('_', '-')}"
            _write_seed_skill(source, root_path / name / "SKILL.md", name)
    return root_path


def reset_hermes_skills(*, source_dir: Path | None = None, root: Path | None = None) -> Path:
    """Reset ProteinClaw's Hermes-backed skills to repo seed text."""
    root_path = hermes_skills_root(root)
    if root_path.exists():
        shutil.rmtree(root_path)
    return ensure_hermes_skills(source_dir=source_dir or _SKILLS_DIR, root=root_path)


def snapshot_hermes_skills(dest_dir: Path, *, root: Path | None = None) -> Path:
    """Copy active Hermes skills into a run directory for reproducibility."""
    root_path = ensure_hermes_skills(root=root)
    dest = Path(dest_dir) / "hermes-skills"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(root_path, dest)
    return dest


def hermes_skills_diff(*, source_dir: Path | None = None, root: Path | None = None) -> str:
    """Return a unified diff between repo seed skills and active Hermes skills."""
    source_dir = source_dir or _SKILLS_DIR
    root_path = ensure_hermes_skills(source_dir=source_dir, root=root)
    tmp = root_path.parent / ".seed-compare"
    if tmp.exists():
        shutil.rmtree(tmp)
    ensure_hermes_skills(source_dir=source_dir, root=tmp)
    chunks: list[str] = []
    for active in sorted(root_path.rglob("SKILL.md")):
        rel = active.relative_to(root_path)
        seed = tmp / rel
        if not seed.exists():
            chunks.append(f"Only in active skills: {rel}\n")
            continue
        a = seed.read_text(encoding="utf-8").splitlines(keepends=True)
        b = active.read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(a, b, fromfile=f"seed/{rel}", tofile=f"active/{rel}"))
    for seed in sorted(tmp.rglob("SKILL.md")):
        rel = seed.relative_to(tmp)
        if not (root_path / rel).exists():
            chunks.append(f"Missing from active skills: {rel}\n")
    shutil.rmtree(tmp, ignore_errors=True)
    return "".join(chunks)


def validate_hermes_skills(*, root: Path | None = None) -> list[str]:
    """Validate active Hermes SKILL.md files; return human-readable errors."""
    root_path = ensure_hermes_skills(root=root)
    errors: list[str] = []
    for skill in sorted(root_path.rglob("SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            errors.append(f"{skill}: missing SKILL.md frontmatter")
            continue
        if "name:" not in text.split("---", 2)[1]:
            errors.append(f"{skill}: missing name in frontmatter")
    return errors


_HERMES_SKILL_GUIDANCE = """

---

## Hermes Skill Evolution

ProteinClaw repo skill files are seed material, not a live write target. For
cross-run durable lessons, use Hermes `skill_manage` to update the active
ProteinClaw skills namespace (`proteinclaw-minibinder`, `proteinclaw-nanobody`,
and `proteinclaw-tool-*`). Keep the existing append-only discipline and the
`## Learned (run ...)` provenance format. Do not use file write/edit tools to
modify `src/proteinclaw/skills`; run-local files remain under the run directory.
"""


def load_skill_text(path: Path = _SKILL_PATH) -> str:
    """Return the core skill text + appended tool/learned index and Hermes guidance."""
    if not path.exists():
        raise SkillLoadError(f"skill file not found at {path}; agent cannot run without it")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SkillLoadError(f"skill file at {path} is empty; agent cannot run without it")
    return text + _tool_skill_index(path.parent) + _HERMES_SKILL_GUIDANCE


__all__ = [
    "SkillLoadError",
    "ensure_hermes_skills",
    "hermes_skills_diff",
    "hermes_skills_root",
    "load_skill_text",
    "reset_hermes_skills",
    "skill_path_for_workflow",
    "snapshot_hermes_skills",
    "validate_hermes_skills",
]

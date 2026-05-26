"""`proteinclaw skills` — inspect/validate/revert the agent's skill edits.

`diff`/`reset` shell out to git; `log` reads the skill files; `check` runs
pytest. Tests point _SKILLS_DIR at a tmp dir to avoid touching the real repo.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import proteinclaw.agent.skills as skills_mod
from proteinclaw import cli

runner = CliRunner()


def test_skills_log_lists_learned_headers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", tmp_path)
    (tmp_path / "tools").mkdir()
    learned = tmp_path / "learned" / "igv.md"
    learned.parent.mkdir()
    learned.write_text(
        "# IgV\n\n## Learned (run abc123, 2026-05-26): IgV grooves like helical binders\nbody\n"
    )
    res = runner.invoke(cli.app, ["skills", "log"])
    assert res.exit_code == 0, res.output
    assert "Learned (run abc123" in res.output
    assert "learned/igv.md" in res.output


def test_skills_log_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", tmp_path)
    res = runner.invoke(cli.app, ["skills", "log"])
    assert res.exit_code == 0
    assert "No agent-recorded" in res.output


def test_skills_diff_not_a_checkout(tmp_path: Path, monkeypatch) -> None:
    # tmp_path is not a git work tree → diff must fail loud, not crash.
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", tmp_path)
    res = runner.invoke(cli.app, ["skills", "diff"])
    assert res.exit_code == 1
    assert "not a git checkout" in res.output


def test_skills_reset_reverts_tracked_and_removes_untracked(tmp_path: Path, monkeypatch) -> None:
    """reset must revert modified tracked skills AND delete the agent's new
    (untracked) skill files — `git checkout` alone leaves untracked files."""
    import subprocess

    sd = tmp_path
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", sd)

    def git(*a: str) -> None:
        subprocess.run(["git", "-C", str(sd), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    tracked = sd / "proteindesign.md"
    tracked.write_text("original\n")
    git("add", ".")
    git("commit", "-q", "-m", "base")

    # Simulate the agent: modify the tracked skill + create a new untracked one.
    tracked.write_text("original\nappended by agent\n")
    new = sd / "learned" / "new-topic.md"
    new.parent.mkdir()
    new.write_text("# new skill\n\n## Learned (run xyz, 2026-05-26): ...\n")

    res = runner.invoke(cli.app, ["skills", "reset", "--yes"])
    assert res.exit_code == 0, res.output
    assert tracked.read_text() == "original\n"   # tracked modification reverted
    assert not new.exists()                       # untracked new skill removed


def test_skills_check_requires_test_suite(tmp_path: Path, monkeypatch) -> None:
    # skills dir whose parents[2] has no tests/ → check errors gracefully.
    sd = tmp_path / "src" / "proteinclaw" / "skills"
    sd.mkdir(parents=True)
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", sd)
    res = runner.invoke(cli.app, ["skills", "check"])
    assert res.exit_code == 1
    assert "source install" in res.output

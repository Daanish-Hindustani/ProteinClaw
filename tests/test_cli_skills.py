"""`proteinclaw skills` — inspect/validate/reset Hermes-backed skills."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from proteinclaw import cli

runner = CliRunner()


def _seed_source(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "proteinclaw" / "skills"
    source.mkdir(parents=True)
    (source / "proteindesign.md").write_text("# mini\n")
    (source / "nanobody.md").write_text("# nano\n")
    (source / "tools").mkdir()
    (source / "tools" / "esmfold.md").write_text("# esm\n")
    return source


def test_skills_log_lists_learned_headers(tmp_path: Path, monkeypatch) -> None:
    import proteinclaw.agent.skills as skills_mod

    source = _seed_source(tmp_path)
    root = tmp_path / "hermes"
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(root))
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", source)
    skills_mod.ensure_hermes_skills(source_dir=source, root=root)
    learned = root / "proteinclaw-minibinder" / "SKILL.md"
    learned.write_text(learned.read_text() + "\n## Learned (run abc123, 2026-05-26): IgV grooves\nbody\n")

    res = runner.invoke(cli.app, ["skills", "log"])
    assert res.exit_code == 0, res.output
    assert "Learned (run abc123" in res.output
    assert "proteinclaw-minibinder/SKILL.md" in res.output


def test_skills_log_empty(tmp_path: Path, monkeypatch) -> None:
    import proteinclaw.agent.skills as skills_mod

    source = _seed_source(tmp_path)
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(tmp_path / "hermes"))
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", source)
    res = runner.invoke(cli.app, ["skills", "log"])
    assert res.exit_code == 0
    assert "No agent-recorded" in res.output


def test_skills_diff_reports_no_changes(tmp_path: Path, monkeypatch) -> None:
    import proteinclaw.agent.skills as skills_mod

    source = _seed_source(tmp_path)
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(tmp_path / "hermes"))
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", source)
    res = runner.invoke(cli.app, ["skills", "diff"])
    assert res.exit_code == 0
    assert "No Hermes skill changes" in res.output


def test_skills_reset_restores_seed(tmp_path: Path, monkeypatch) -> None:
    import proteinclaw.agent.skills as skills_mod

    source = _seed_source(tmp_path)
    root = tmp_path / "hermes"
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(root))
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", source)
    skills_mod.ensure_hermes_skills(source_dir=source, root=root)
    mini = root / "proteinclaw-minibinder" / "SKILL.md"
    mini.write_text(mini.read_text() + "\nchanged\n")

    res = runner.invoke(cli.app, ["skills", "reset", "--yes"])
    assert res.exit_code == 0, res.output
    assert "changed" not in mini.read_text()


def test_skills_check_validates_frontmatter(tmp_path: Path, monkeypatch) -> None:
    import proteinclaw.agent.skills as skills_mod

    source = _seed_source(tmp_path)
    root = tmp_path / "hermes"
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(root))
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", source)
    res = runner.invoke(cli.app, ["skills", "check"])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output

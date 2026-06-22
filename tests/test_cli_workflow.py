"""`proteinclaw run --workflow` selects the nanobody vs mini-binder core skill."""

from __future__ import annotations

from typer.testing import CliRunner

from proteinclaw import cli

runner = CliRunner()


def test_workflow_nanobody_dry_run_selects_nanobody_skill() -> None:
    result = runner.invoke(
        cli.app,
        ["run", "design a nanobody against MRGPRX2",
         "--workflow", "nanobody", "--dry-run", "--skip-doctor"],
    )
    assert result.exit_code == 0, result.output
    assert "workflow=nanobody" in result.output
    assert "design.nanobody_library" in result.output


def test_workflow_defaults_to_minibinder() -> None:
    result = runner.invoke(
        cli.app, ["run", "design a binder", "--dry-run", "--skip-doctor"]
    )
    assert result.exit_code == 0, result.output
    assert "workflow=minibinder" in result.output


def test_workflow_rejects_unknown_value() -> None:
    result = runner.invoke(
        cli.app, ["run", "x", "--workflow", "bogus", "--dry-run", "--skip-doctor"]
    )
    assert result.exit_code == 1
    assert "unknown --workflow" in result.output

"""``proteinclaw`` CLI — entry point.

In Phase 1, the CLI exposes ``--version``, ``--help``, and the ``doctor``
subcommand. ``run`` / ``history`` / ``show`` / ``cancel`` (PRD §11) are
stubbed and refuse with a clear ``not yet implemented`` message until their
phases land. This is deliberate: per CLAUDE.md "Honesty about implementation
state", a stub that errors loudly beats a silent half-feature.
"""

from __future__ import annotations

import sys
from typing import Optional

import typer

from proteinclaw import __version__
from proteinclaw.doctor import run_doctor

app = typer.Typer(
    name="proteinclaw",
    help="Agentic CLI for protein binder design.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"proteinclaw {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """proteinclaw — Gemini-powered protein binder design pipeline."""
    return None


@app.command("doctor")
def doctor_cmd(
    self_test: bool = typer.Option(
        False,
        "--self-test",
        help="Run the full tool-level integration suite (requires GPU + Docker).",
    ),
) -> None:
    """Check that the local environment can run proteinclaw."""
    exit_code = run_doctor(self_test=self_test)
    raise typer.Exit(code=exit_code)


@app.command("run")
def run_cmd(prompt: str) -> None:
    """Run a binder-design campaign (NOT YET IMPLEMENTED — lands in Phase 8/10)."""
    typer.echo(
        "Error: `proteinclaw run` is not implemented yet — Phase 1 scaffolding "
        "only. See PLAN.md Task 10 for the implementation milestone.",
        err=True,
    )
    raise typer.Exit(code=2)


@app.command("history")
def history_cmd() -> None:
    """List past runs (NOT YET IMPLEMENTED — lands in Phase 9)."""
    typer.echo("Error: `proteinclaw history` lands in Phase 9.", err=True)
    raise typer.Exit(code=2)


@app.command("show")
def show_cmd(run_id: str) -> None:
    """Open report.html for a run (NOT YET IMPLEMENTED — lands in Phase 9)."""
    typer.echo("Error: `proteinclaw show` lands in Phase 9.", err=True)
    raise typer.Exit(code=2)


@app.command("cancel")
def cancel_cmd(run_id: str) -> None:
    """Cancel an in-flight run (NOT YET IMPLEMENTED — lands in Phase 8/10)."""
    typer.echo("Error: `proteinclaw cancel` lands in Phase 8/10.", err=True)
    raise typer.Exit(code=2)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject)."""
    app()


if __name__ == "__main__":
    main()

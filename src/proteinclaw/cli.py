"""``proteinclaw`` CLI — entry point.

In Phase 1, the CLI exposes ``--version``, ``--help``, and the ``doctor``
subcommand. ``run`` / ``history`` / ``show`` / ``cancel`` (PRD §11) are
stubbed and refuse with a clear ``not yet implemented`` message until their
phases land. This is deliberate: per CLAUDE.md "Honesty about implementation
state", a stub that errors loudly beats a silent half-feature.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from proteinclaw import __version__
from proteinclaw.doctor import doctor_ok, run_doctor

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
    """proteinclaw — Claude-powered protein binder design pipeline."""
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
def run_cmd(
    prompt: str = typer.Argument(..., help="Natural-language binder design goal."),
    output_dir: Path = typer.Option(
        Path("./runs"),
        "--output-dir",
        "-o",
        help="Where to write run artifacts (one subdirectory per run).",
    ),
    max_turns: int = typer.Option(
        60,
        "--max-turns",
        help="Agent turn cap (one turn = one tool call OR one assistant text).",
    ),
    model: str = typer.Option(
        "claude-opus-4-7",
        "--model",
        help="Claude model id.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build the system prompt + tool catalogue and exit without calling the SDK.",
    ),
    show_reasoning: bool = typer.Option(
        False,
        "--show-reasoning",
        help="Stream assistant text + thinking + tool calls to stdout as they happen.",
    ),
    skip_doctor: bool = typer.Option(
        False,
        "--skip-doctor",
        help="Bypass the `doctor_ok` marker check. For dev/test only.",
    ),
) -> None:
    """Run an autonomous binder-design campaign."""
    if not skip_doctor and not doctor_ok():
        typer.echo(
            "Error: `proteinclaw doctor` has not passed on this machine. "
            "Run it first; it must succeed before `proteinclaw run` is allowed. "
            "Pass --skip-doctor to override (dev only).",
            err=True,
        )
        raise typer.Exit(code=1)

    # Lazy imports — keep --help fast and dry-run-able without the SDK installed.
    from proteinclaw.agent.core import run_campaign
    from proteinclaw.agent.mcp_tools import build_mcp_server
    from proteinclaw.agent.skills import load_skill_text

    if dry_run:
        skill = load_skill_text()
        from proteinclaw.tools import registry

        tool_names = sorted(
            t.name for t in registry.list_tools() if t.category != "debug"
        )
        typer.echo(f"DRY RUN — would invoke model={model} max_turns={max_turns}")
        typer.echo(f"output_dir: {output_dir.resolve()}")
        typer.echo(f"skill chars: {len(skill)}")
        typer.echo(f"tools exposed ({len(tool_names)}): {tool_names}")
        typer.echo(f"prompt: {prompt}")
        raise typer.Exit(code=0)

    def _streamer(kind: str, payload: str) -> None:
        if show_reasoning:
            typer.echo(f"[{kind}] {payload}", err=False)

    summary = run_campaign(
        prompt=prompt,
        output_dir=output_dir,
        model=model,
        max_turns=max_turns,
        on_stream_chunk=_streamer if show_reasoning else None,
    )

    typer.echo("")
    typer.echo("=== run complete ===")
    typer.echo(f"run_id:          {summary.run_id}")
    typer.echo(f"session_id:      {summary.session_id}")
    typer.echo(f"output_dir:      {summary.output_dir}")
    typer.echo(f"turns:           {summary.num_turns}")
    typer.echo(f"tool calls:      {summary.num_tool_calls} ({summary.num_tool_errors} errored)")
    typer.echo(f"total_cost_usd:  {summary.total_cost_usd}")
    typer.echo(f"elapsed:         {summary.elapsed_wall_s:.1f}s")
    if summary.failure_reason:
        typer.echo(f"failure:         {summary.failure_reason}", err=True)
        raise typer.Exit(code=1)
    if summary.final_text:
        typer.echo("\nfinal:")
        typer.echo(summary.final_text)


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

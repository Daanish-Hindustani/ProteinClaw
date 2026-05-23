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
        help="Per-round agent turn cap (multiplied by --rounds).",
    ),
    rounds: int = typer.Option(
        1,
        "--rounds",
        "-r",
        help="Iteration budget. After round 1 the agent may refine RFD3 params and re-run.",
        min=1,
        max=5,
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
        typer.echo(
            f"DRY RUN — model={model} rounds={rounds} max_turns_per_round={max_turns}"
        )
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
        rounds=rounds,
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
def history_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show."),
    target: Optional[str] = typer.Option(
        None, "--target", help="Filter by exact target_pdb_id."
    ),
) -> None:
    """List past runs from the SQLite history at ~/.proteinclaw/runs.db."""
    from proteinclaw import db

    with db.connect() as conn:
        rows = db.list_runs(conn, limit=limit, target=target)

    if not rows:
        typer.echo("(no runs found)")
        return

    headers = ("run_id", "status", "target", "designs", "cost_usd", "elapsed_s", "prompt")
    fmt = "{:<14}  {:<10}  {:<6}  {:>7}  {:>9}  {:>9}  {}"
    typer.echo(fmt.format(*headers))
    typer.echo("-" * 110)
    for r in rows:
        cost = f"{r['total_cost_usd']:.3f}" if r["total_cost_usd"] is not None else "-"
        elapsed = f"{r['elapsed_s']:.1f}" if r["elapsed_s"] is not None else "-"
        prompt = (r["prompt"] or "")[:48]
        typer.echo(
            fmt.format(
                r["run_id"][:14],
                (r["status"] or "")[:10],
                (r["target_pdb_id"] or "-")[:6],
                r["num_designs"] or 0,
                cost,
                elapsed,
                prompt,
            )
        )


@app.command("show")
def show_cmd(
    run_id: str = typer.Argument(..., help="Run id from `proteinclaw history`."),
    json_out: bool = typer.Option(
        False, "--json", help="Print the run+designs record as JSON instead of opening the report."
    ),
) -> None:
    """Show a run summary; opens report.html if it exists."""
    import webbrowser

    from proteinclaw import db

    with db.connect() as conn:
        record = db.get_run(conn, run_id)

    if record is None:
        typer.echo(f"Error: run {run_id!r} not found", err=True)
        raise typer.Exit(code=1)

    if json_out:
        typer.echo(json.dumps(record, default=str, indent=2))
        return

    run = record["run"]
    typer.echo(f"run_id:      {run['run_id']}")
    typer.echo(f"status:      {run['status']}")
    typer.echo(f"prompt:      {run['prompt']}")
    typer.echo(f"target:      {run['target_pdb_id'] or '-'}  chain={run['target_chain'] or '-'}  crop={run['target_crop'] or '-'}")
    typer.echo(f"output_dir:  {run['output_dir']}")
    typer.echo(f"turns:       {run['num_turns']}")
    typer.echo(f"designs:     {run['num_designs']}")
    typer.echo(f"cost_usd:    {run['total_cost_usd']}")
    typer.echo(f"elapsed_s:   {run['elapsed_s']}")
    if run.get("failure_reason"):
        typer.echo(f"failure:     {run['failure_reason']}")

    if record["designs"]:
        typer.echo("\ndesigns (ranked):")
        for d in record["designs"]:
            typer.echo(
                f"  rank={d['rank']:>3}  esm={d['plddt_esm_monomer']}  "
                f"af2_complex={d['plddt_af2_complex']}  pdb={d['pdb_path']}"
            )

    report = Path(run["output_dir"]) / "report.html"
    if report.exists():
        typer.echo(f"\nopening report.html → {report}")
        try:
            webbrowser.open(report.as_uri())
        except Exception:  # noqa: BLE001
            typer.echo(f"(open manually: {report})", err=True)
    else:
        typer.echo("\n(no report.html yet — Phase 6 wires this up)")


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

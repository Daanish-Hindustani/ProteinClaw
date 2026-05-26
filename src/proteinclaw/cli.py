"""``proteinclaw`` CLI — entry point.

Exposes ``--version``, ``--help``, and the ``doctor`` / ``run`` / ``history``
/ ``show`` / ``cancel`` subcommands (PRD §11). ``cancel`` finds an in-flight
run's labelled GPU containers, ``docker kill``s them, SIGTERMs the recorded
driver pid, and marks the run ``cancelled`` in the history DB.
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


@app.command("setup")
def setup_cmd(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Auto-confirm all install/login prompts (non-interactive).",
    ),
    skip_doctor: bool = typer.Option(
        False,
        "--skip-doctor",
        help="Skip the final `proteinclaw doctor` preflight at the end.",
    ),
) -> None:
    """Walk through Claude subscription login + local tool installation."""
    from proteinclaw.setup import run_setup

    raise typer.Exit(code=run_setup(auto=yes, skip_doctor=skip_doctor))


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
        12,
        "--rounds",
        "-r",
        help="Hypothesis-cycle budget (deliberate → run → evaluate). The agent "
        "stops early when the quality gate is met.",
        min=1,
        max=50,
    ),
    no_cap: bool = typer.Option(
        False,
        "--no-cap/--cap",
        help="Lift the hard round ceiling — the agent self-paces against the "
        "quality gate (bounded by a large turn sentinel).",
    ),
    research_fanout: bool = typer.Option(
        True,
        "--research-fanout/--no-research-fanout",
        help="Spawn parallel read-only research scout subagents for "
        "hypothesis-driven planning.",
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
        round_cap = "none (--no-cap)" if no_cap else str(rounds)
        typer.echo(
            f"DRY RUN — model={model} rounds={rounds} max_turns_per_round={max_turns}"
        )
        typer.echo(f"round_cap: {round_cap}")
        typer.echo(f"research_fanout: {research_fanout}")
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
        cap=not no_cap,
        research_fanout=research_fanout,
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
    if summary.skill_edits:
        typer.echo(f"skills evolved:  {len(summary.skill_edits)} file(s) — review with `proteinclaw skills diff`")
        for p in summary.skill_edits:
            typer.echo(f"  - {p}")
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


def _kill_session_containers(session_id: str) -> list[str]:
    """``docker kill`` any running containers labelled with this campaign session.

    Returns the container ids that were targeted. Best-effort: a missing docker
    binary or a docker error yields an empty list rather than raising — cancel
    still proceeds to signal the driver and mark the run cancelled.
    """
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        return []
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label=proteinclaw.session={session_id}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    ids = [cid for cid in result.stdout.split() if cid]
    for cid in ids:
        try:
            subprocess.run(["docker", "kill", cid], capture_output=True, text=True, timeout=15, check=False)
        except (subprocess.SubprocessError, OSError):
            pass
    return ids


def _terminate_run_process(pid: Optional[int]) -> bool:
    """SIGTERM the run's driver process so it stops the agent loop. Best-effort.

    Returns True if a live process was signalled. A ``NULL`` pid (run predates
    pid-tracking) or an already-dead/foreign process returns False.
    """
    import os
    import signal

    if not pid:
        return False
    try:
        os.kill(int(pid), signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, ValueError, OSError):
        return False


@app.command("cancel")
def cancel_cmd(run_id: str) -> None:
    """Cancel an in-flight run: kill its GPU containers, signal its driver, mark cancelled."""
    from proteinclaw import db

    with db.connect() as conn:
        record = db.get_run(conn, run_id)
    if record is None:
        typer.echo(f"Error: run {run_id!r} not found", err=True)
        raise typer.Exit(code=1)

    run = record["run"]
    if run["status"] != "running":
        typer.echo(f"Run {run_id} is not in-flight (status={run['status']}). Nothing to cancel.")
        raise typer.Exit(code=0)

    killed = _kill_session_containers(run["session_id"])
    signalled = _terminate_run_process(run.get("pid"))

    with db.connect() as conn:
        db.record_run_end(
            conn,
            run_id=run["run_id"],
            status="cancelled",
            failure_reason="cancelled by user via `proteinclaw cancel`",
        )

    typer.echo(f"Cancelled run {run_id}.")
    typer.echo(f"  containers killed: {len(killed)}" + (f" ({', '.join(c[:12] for c in killed)})" if killed else ""))
    typer.echo(f"  driver process signalled: {'yes' if signalled else 'no (pid unknown or already exited)'}")


# ---------------------------------------------------------------------------
# `proteinclaw skills` — inspect / validate / revert the agent's
# self-evolution edits to its own skill files (see proteindesign.md
# "Self-evolution"). Edits are append-only and land in src/proteinclaw/skills/.
# ---------------------------------------------------------------------------

skills_app = typer.Typer(
    name="skills",
    help="Inspect, validate, or revert the agent's self-evolution skill edits.",
    no_args_is_help=True,
)
app.add_typer(skills_app, name="skills")


def _skills_dir() -> Path:
    from proteinclaw.agent.skills import _SKILLS_DIR

    return _SKILLS_DIR


def _git_skills(*args: str):
    """Run ``git -C <skills_dir> <args>``; return CompletedProcess, or None if
    git is unavailable or the skills dir isn't inside a git work tree."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        return None
    sd = str(_skills_dir())
    inside = subprocess.run(
        ["git", "-C", sd, "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    return subprocess.run(["git", "-C", sd, *args], capture_output=True, text=True)


def _require_checkout():
    res = _git_skills("rev-parse", "--show-toplevel")
    if res is None:
        typer.echo(
            "Error: the skills dir is not a git checkout. Self-evolution review "
            "(diff/reset) requires a source/editable install of proteinclaw.",
            err=True,
        )
        raise typer.Exit(code=1)


@skills_app.command("diff")
def skills_diff() -> None:
    """Show the agent's uncommitted edits to the skill files."""
    _require_checkout()
    res = _git_skills("diff", "--", ".")
    out = (res.stdout if res else "").strip()
    typer.echo(out if out else "No uncommitted skill changes.")


@skills_app.command("log")
def skills_log() -> None:
    """List the agent's `## Learned (run …)` provenance headers across skills."""
    sd = _skills_dir()
    found = False
    for md in sorted(sd.rglob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.startswith("## Learned (run "):
                typer.echo(f"{md.relative_to(sd)}: {line[3:].strip()}")
                found = True
    if not found:
        typer.echo("No agent-recorded `## Learned` notes found in the skills.")


@skills_app.command("reset")
def skills_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Discard the agent's uncommitted skill edits: revert modified tracked
    files AND remove newly-created (untracked) skill files.

    The agent's "create a new skill" path produces *untracked* files, which
    `git checkout` alone won't remove — so reset also `git clean`s the skills
    tree. Both are scoped to the skills dir.
    """
    _require_checkout()
    status = _git_skills("status", "--porcelain", "--", ".")
    if not (status and status.stdout.strip()):
        typer.echo("No uncommitted skill changes to reset.")
        return
    if not yes and not typer.confirm(
        "Discard all uncommitted skill edits — revert modified files AND "
        "delete untracked new skill files?"
    ):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)
    _git_skills("checkout", "--", ".")          # revert tracked modifications
    _git_skills("clean", "-fd", "--", ".")      # remove untracked new skills (e.g. learned/*.md)
    typer.echo("Skill files restored to the last commit (untracked skills removed).")


@skills_app.command("check")
def skills_check() -> None:
    """Validate the (possibly edited) skills against the invariant test suite."""
    import subprocess

    repo_root = _skills_dir().parents[2]  # .../ProteinClaw
    tests = ["tests/agent/test_skill_invariants.py", "tests/agent/test_skills.py"]
    if not all((repo_root / t).exists() for t in tests):
        typer.echo(
            "Error: skill invariant tests not found — `skills check` needs a "
            "source install with the test suite present.",
            err=True,
        )
        raise typer.Exit(code=1)
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests], cwd=str(repo_root))
    raise typer.Exit(code=proc.returncode)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject)."""
    app()


if __name__ == "__main__":
    main()

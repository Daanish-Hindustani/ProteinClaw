"""ProteinClaw CLI — argparse dispatch.

Subcommands:

- ``setup``  — interactive first-run wizard (prompts + optional install).
- ``doctor`` — system probe; exit code reflects readiness.
- ``run``    — execute one prompt end-to-end.
- ``run -i`` — interactive REPL.

The CLI gates `run` on a successfully completed setup. `doctor` works
regardless so users can diagnose a half-configured box.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from proteinclaw import __version__
from proteinclaw.benchmark.compare import compare_reports
from proteinclaw.benchmark.models import BenchmarkReport
from proteinclaw.benchmark.runner import load_suite, run_suite
from proteinclaw.cli import _console as c
from proteinclaw.cli.config import (
    ConfigError,
    config_exists,
    load_config,
    redact,
)
from proteinclaw.cli.doctor import CheckStatus, run_doctor
from proteinclaw.cli.runner import run_interactive, run_one_shot
from proteinclaw.cli.wizard import run_wizard


def main(argv: Sequence[str] | None = None) -> int:
    """ProteinClaw CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = args.func  # set by each subcommand
    return int(handler(args) or 0)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the root argparse parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="proteinclaw",
        description="ProteinClaw — agentic protein-design CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"proteinclaw {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    setup_p = sub.add_parser("setup", help="Run the interactive setup wizard.")
    setup_p.set_defaults(func=_cmd_setup)

    doctor_p = sub.add_parser("doctor", help="Probe the system for readiness.")
    doctor_p.set_defaults(func=_cmd_doctor)

    run_p = sub.add_parser("run", help="Run a prompt end-to-end.")
    group = run_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", "-p", help="One-shot prompt to execute.")
    group.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Start an interactive prompt loop.",
    )
    run_p.add_argument(
        "--fanout",
        type=int,
        default=None,
        help="Concurrent root branches per task. Defaults to MAX_FANOUT.",
    )
    run_p.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Orchestrator iterations per task. Defaults to MAX_ITERATIONS.",
    )
    run_p.set_defaults(func=_cmd_run)

    bench_p = sub.add_parser("benchmark", help="Run and compare benchmark suites.")
    bench_sub = bench_p.add_subparsers(dest="benchmark_cmd", required=True)

    bench_run = bench_sub.add_parser("run", help="Run a benchmark suite.")
    bench_run.add_argument("--suite", required=True, help="Path to benchmark suite YAML.")
    bench_run.add_argument("--out", required=True, help="Path to write benchmark report JSON.")
    bench_run.set_defaults(func=_cmd_benchmark_run)

    bench_compare = bench_sub.add_parser("compare", help="Compare two benchmark reports.")
    bench_compare.add_argument("old", help="Old/baseline benchmark report JSON.")
    bench_compare.add_argument("new", help="New benchmark report JSON.")
    bench_compare.set_defaults(func=_cmd_benchmark_compare)

    return parser


def _cmd_setup(args: argparse.Namespace) -> int:
    """Run the wizard. Surfaces SystemExit codes from the wizard's hard gates."""
    del args
    try:
        run_wizard()
    except SystemExit as e:
        return int(e.code or 1)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Print the doctor table. Exit non-zero on any FAIL."""
    del args
    report = run_doctor()
    c.header("Doctor")
    for ck in report.checks:
        text = f"{ck.name}: {ck.detail}" if ck.detail else ck.name
        if ck.status is CheckStatus.OK:
            c.ok(text)
        elif ck.status is CheckStatus.WARN:
            c.warn(text)
        elif ck.status is CheckStatus.SKIP:
            c.info(c.dim(f"skip — {text}"))
        else:
            c.err(text)
            if ck.fix_hint:
                c.info(f"  fix: {ck.fix_hint}")
    if config_exists():
        try:
            cfg = load_config()
        except ConfigError as e:
            c.err(str(e))
        else:
            c.info(f"config: {redact(cfg)}")
    return 1 if report.has_failures else 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Run a prompt — gates on a valid config."""
    try:
        cfg = load_config()
    except ConfigError as e:
        c.err(str(e))
        c.info("Run `proteinclaw setup` first.")
        return 2
    if args.interactive:
        return run_interactive(cfg, fanout=args.fanout, iterations=args.iterations)
    return run_one_shot(
        cfg, args.prompt, fanout=args.fanout, iterations=args.iterations
    )


def _cmd_benchmark_run(args: argparse.Namespace) -> int:
    """Run a benchmark suite and write a JSON report."""
    try:
        cfg = load_config()
    except ConfigError as e:
        c.err(str(e))
        c.info("Run `proteinclaw setup` first.")
        return 2

    try:
        suite = load_suite(Path(args.suite))
        report = asyncio.run(run_suite(cfg, suite))
        out = Path(args.out)
        report.write_json(out)
    except Exception as e:
        c.err(f"benchmark failed: {e}")
        return 1

    c.header("Benchmark")
    c.ok(
        f"suite={report.suite_id} tasks={len(report.task_results)} "
        f"success_rate={report.success_rate:.1%}"
    )
    for result in report.task_results:
        c.info(
            f"{result.task_id}: verdict={result.verdict} "
            f"winner={result.winner_branch_id} elapsed={result.elapsed_seconds:.2f}s"
        )
    c.info(f"report written to {out}")
    return 0


def _cmd_benchmark_compare(args: argparse.Namespace) -> int:
    """Compare two benchmark reports."""
    try:
        old = BenchmarkReport.from_json_file(Path(args.old))
        new = BenchmarkReport.from_json_file(Path(args.new))
    except Exception as e:
        c.err(f"could not load benchmark reports: {e}")
        return 1

    comparison = compare_reports(old, new)
    c.header("Benchmark Compare")
    c.info(
        f"success_rate: {comparison.old_success_rate:.1%} -> "
        f"{comparison.new_success_rate:.1%} "
        f"({comparison.new_success_rate - comparison.old_success_rate:+.1%})"
    )
    if comparison.verdict_count_deltas:
        c.info(f"verdict deltas: {comparison.verdict_count_deltas}")
    if comparison.average_metric_deltas:
        c.info(f"average metric deltas: {comparison.average_metric_deltas}")
    for delta in comparison.task_deltas:
        if not delta.changed:
            continue
        c.info(
            f"{delta.task_id}: {delta.old_verdict} -> {delta.new_verdict} "
            f"metrics={delta.metric_deltas}"
        )
    if comparison.missing_in_new:
        c.warn(f"missing in new: {', '.join(comparison.missing_in_new)}")
    if comparison.added_in_new:
        c.info(f"added in new: {', '.join(comparison.added_in_new)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())

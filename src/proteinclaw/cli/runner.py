"""End-to-end runner: builds the system and dispatches a query.

`run_one_shot()` runs a single prompt through the orchestrator and
prints the result. `run_interactive()` is a tiny REPL that loops on
prompts until the user exits.

The runner is the only place in the CLI where every component is
constructed together: tool registry, skill library, evaluator, memory
stores, planner (with LLM), orchestrator. Errors at any layer surface
as user-readable messages.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from proteinclaw.agents.branching_service import BranchingService
from proteinclaw.agents.sub_agent import SubAgent
from proteinclaw.cli import _console as c
from proteinclaw.cli.config import Config
from proteinclaw.common.litellm_client import LiteLLMClient
from proteinclaw.evaluation.evaluator import EvaluationConfig, Evaluator
from proteinclaw.memory.knowledge_store import SQLiteKnowledgeStore
from proteinclaw.memory.memory_manager import MemoryManager
from proteinclaw.memory.session_store import SQLiteSessionStore
from proteinclaw.memory.trace_store import SQLiteTraceStore
from proteinclaw.orchestrator.orchestrator import Orchestrator
from proteinclaw.orchestrator.planner import Planner
from proteinclaw.skills.skill_library import SkillLibrary
from proteinclaw.tools.factory import build_default_registry


def _repo_root() -> Path:
    """Return the repo root by walking up from this file."""
    return Path(__file__).resolve().parents[3]


def _seeds_dir() -> Path:
    """Path to the bundled seed skill markdown files."""
    return _repo_root() / "src" / "proteinclaw" / "skills" / "protein_design"


def _eval_config_path() -> Path:
    """Path to the bundled evaluator threshold YAML."""
    return _repo_root() / "config" / "evaluation.yaml"


def _state_dir() -> Path:
    """Where to keep per-session SQLite databases.

    Honours ``$XDG_DATA_HOME`` (defaults to ``$HOME/.local/share``).
    """
    raw = os.environ.get("XDG_DATA_HOME")
    base = Path(raw) if raw else Path.home() / ".local" / "share"
    return base / "proteinclaw" / "state"


def _build_orchestrator(config: Config) -> tuple[Orchestrator, MemoryManager, str]:
    """Construct the full system. Returns (orchestrator, memory, db_dir)."""
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    knowledge = SQLiteKnowledgeStore(state_dir / "knowledge.db")
    sessions = SQLiteSessionStore(state_dir / "sessions.db")
    traces = SQLiteTraceStore(state_dir / "traces.db")
    memory = MemoryManager(knowledge=knowledge, sessions=sessions, traces=traces)

    # Tool config from the user's setup. PROTEINCLAW_BACKEND comes from the
    # env file the install script wrote; we re-export the API key for any
    # backend that wants it.
    os.environ.setdefault("ANTHROPIC_API_KEY", config.ai_api_key)
    if config.tools_install_root:
        os.environ.setdefault(
            "RFDIFFUSION_PATH", str(Path(config.tools_install_root) / "RFdiffusion")
        )
        os.environ.setdefault(
            "PROTEINMPNN_PATH", str(Path(config.tools_install_root) / "ProteinMPNN")
        )

    registry = build_default_registry()
    library = SkillLibrary.from_directory(_seeds_dir())
    # One LLM client serves both planner (decomposition) and sub-agent
    # (tool-calling). Reusing the client keeps connection pools warm.
    llm = LiteLLMClient(api_key=config.ai_api_key, model=config.ai_model)
    sub_agent = SubAgent(
        registry=registry,
        skill_library=library,
        trace_store=traces,
        llm=llm,
    )
    branching = BranchingService(sub_agent=sub_agent, trace_store=traces)
    evaluator = Evaluator(
        name="default",
        config=EvaluationConfig.from_yaml(_eval_config_path()),
    )
    planner = Planner(llm=llm)
    orch = Orchestrator(
        planner=planner,
        branching_service=branching,
        evaluator=evaluator,
        session_store=sessions,
        trace_store=traces,
    )
    return orch, memory, str(state_dir)


def run_one_shot(
    config: Config,
    prompt: str,
    *,
    fanout: int | None = None,
    iterations: int | None = None,
) -> int:
    """Run `prompt` once, print results, return an exit code."""
    return asyncio.run(_run_async(config, prompt, fanout=fanout, iterations=iterations))


async def _run_async(
    config: Config,
    prompt: str,
    *,
    fanout: int | None,
    iterations: int | None,
) -> int:
    orch, _, db_dir = _build_orchestrator(config)
    c.header("Running")
    c.info(f"prompt: {prompt!r}")
    c.info(f"model:  {config.ai_model}")
    c.info(f"state:  {db_dir}")
    if fanout is not None or iterations is not None:
        c.info(f"caps:   fanout={fanout or 'default'} iterations={iterations or 'default'}")
    try:
        session = await orch.run(prompt, fanout=fanout, iterations=iterations)
    except Exception as e:
        c.err(f"orchestrator failed: {e}")
        return 1
    _print_session(session.session_id, session.final_payload or {})
    c.info(f"trace stored at {db_dir}/traces.db (session_id={session.session_id})")
    return 0


def run_interactive(
    config: Config,
    *,
    fanout: int | None = None,
    iterations: int | None = None,
) -> int:
    """Loop on prompts until the user exits with /quit, EOF, or Ctrl-C."""
    return asyncio.run(_interactive_async(config, fanout=fanout, iterations=iterations))


async def _interactive_async(
    config: Config,
    *,
    fanout: int | None,
    iterations: int | None,
) -> int:
    orch, _, db_dir = _build_orchestrator(config)
    c.header("ProteinClaw — interactive")
    c.info(f"state dir: {db_dir}")
    c.info("type a prompt and press enter; /quit (or Ctrl-D) to exit")
    while True:
        try:
            prompt = await asyncio.to_thread(input, c.bold("\nproteinclaw> "))
            prompt = prompt.strip()
        except (EOFError, KeyboardInterrupt):
            print()  # newline after the ^C / ^D
            c.info("bye.")
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"/quit", "/exit", "quit", "exit"}:
            c.info("bye.")
            return 0
        try:
            session = await orch.run(prompt, fanout=fanout, iterations=iterations)
        except Exception as e:
            c.err(f"orchestrator failed: {e}")
            continue
        _print_session(session.session_id, session.final_payload or {})


def _print_session(session_id: str, payload: dict[str, Any]) -> None:
    """Render the orchestrator's final payload as a human-readable report.

    Per task we emit:

    1. A status line (verdict + iterations + winner branch id).
    2. The evaluator's critique summary.
    3. A "Metrics" block with each metric's observed value and pass/fail.
    4. A "Designs" block surfacing the winning branch's top backbone,
       top designed sequence, predicted fold, and closest foldseek hit
       — whichever of those the winner produced.
    5. Weaknesses + suggestions when the evaluator returned them — these
       are the actionable hooks for a follow-up run.
    """
    c.header("Result")
    c.info(f"session_id: {session_id}")
    tasks = payload.get("tasks") or []
    if not tasks:
        c.warn("no tasks in final payload — check the trace for failures")
        return
    for i, task in enumerate(tasks, start=1):
        _print_task_report(i, task)


def _print_task_report(idx: int, task: dict[str, Any]) -> None:
    """Render one task block of the end-of-run report."""
    verdict = task.get("verdict", "unknown")
    iterations = task.get("iterations_used", "?")
    winner = task.get("winner_branch_id")
    desc = (task.get("description") or "").strip()
    passed = task.get("passed_metrics") or []
    summary = (task.get("summary") or "").strip()
    metric_scores = task.get("metric_scores") or []
    winner_payload = task.get("winner_payload") or {}
    weaknesses = task.get("weaknesses") or []
    suggestions = task.get("suggestions") or []

    line = (
        f"task #{idx}: verdict={verdict} winner={winner} "
        f"iterations={iterations} passed={len(passed)}/{len(metric_scores) or '?'}"
    )
    if verdict == "stop_success":
        c.ok(line)
    elif verdict == "stop_failure":
        c.err(line)
    else:
        c.warn(line)
    if desc:
        print(c.dim(f"   prompt: {desc}"))
    if summary:
        print(c.dim(f"   {summary}"))

    if metric_scores:
        print(c.bold("   Metrics:"))
        for m in metric_scores:
            mark = "✓" if m.get("passed") else ("·" if m.get("passed") is None else "✗")
            value = m.get("value")
            value_str = f"{value:.3f}" if isinstance(value, (int, float)) else str(value)
            print(f"     {mark} {m.get('metric'):<22} {value_str}")

    if winner_payload:
        print(c.bold("   Designs:"))
        tb = winner_payload.get("top_backbone")
        if tb:
            print(
                f"     • backbone {tb.get('design_id')} "
                f"(plddt≈{tb.get('plddt_estimate')!r}) {tb.get('pdb_path')}"
            )
        if winner_payload.get("num_backbones"):
            print(c.dim(f"        ({winner_payload['num_backbones']} total)"))
        ts = winner_payload.get("top_sequence")
        if ts:
            seq = ts.get("sequence") or ""
            shown = seq if len(seq) <= 80 else seq[:77] + "..."
            print(f"     • sequence (score={ts.get('score'):.3f}): {shown}")
        if winner_payload.get("num_sequences"):
            print(c.dim(f"        ({winner_payload['num_sequences']} total)"))
        fold = winner_payload.get("fold")
        if fold:
            bits = []
            if "plddt" in fold:
                bits.append(f"plddt={fold['plddt']:.3f}")
            if "ptm" in fold:
                bits.append(f"ptm={fold['ptm']:.3f}")
            if "pdb_path" in fold:
                bits.append(fold["pdb_path"])
            print(f"     • fold: {' '.join(bits)}")
        hit = winner_payload.get("foldseek_top_hit")
        if hit:
            tm = hit.get("tm_score")
            tm_str = f"{tm:.3f}" if isinstance(tm, (int, float)) else str(tm)
            print(f"     • novelty: closest hit {hit.get('target')} (TM={tm_str})")
        tools = winner_payload.get("tools") or []
        if tools:
            print(c.dim(f"     tools used: {', '.join(tools)}"))

    if weaknesses:
        print(c.bold("   Weaknesses:"))
        for w in weaknesses[:5]:
            print(f"     - {w}")
    if suggestions:
        print(c.bold("   Suggestions:"))
        for s in suggestions[:5]:
            print(f"     - {s}")

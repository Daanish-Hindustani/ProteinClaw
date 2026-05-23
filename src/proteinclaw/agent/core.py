"""Agent driver — Claude Agent SDK loop, skill-prompt assembly, trace stream.

Public entry point: ``run_campaign(prompt, output_dir, ...)``.

Wires:
  * ``skills.load_skill_text()`` for the skill file (appended to default
    Claude Code system prompt).
  * ``mcp_tools.build_mcp_server()`` for the in-process MCP exposing
    every registered tool.
  * ``trace.TraceWriter`` for the append-only run log.
  * ``ClaudeSDKClient`` for the multi-turn loop (session cache persists,
    so the ~$0.15 cache-priming cost amortises across all turns).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from proteinclaw import db
from proteinclaw.agent.mcp_tools import (
    MCP_SERVER_NAME,
    allowed_tool_glob,
    build_mcp_server,
)
from proteinclaw.agent.skills import load_skill_text
from proteinclaw.agent.trace import TraceWriter
from proteinclaw.runner.local import DEFAULT_WORKSPACE_ROOT
from proteinclaw.runner.router import ComputeRouter

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TURNS = 60


@dataclass
class RunPaths:
    """On-disk layout for one ``proteinclaw run`` invocation."""

    run_id: str
    session_id: str
    output_dir: Path
    trace_jsonl: Path
    plan_md: Path
    designs_dir: Path
    workspace: Path


def mint_run_paths(
    output_dir: Path,
    *,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> RunPaths:
    rid = run_id or uuid.uuid4().hex[:12]
    sid = session_id or rid
    odir = Path(output_dir).expanduser().resolve() / rid
    odir.mkdir(parents=True, exist_ok=True)
    designs = odir / "designs"
    designs.mkdir(parents=True, exist_ok=True)
    workspace = (DEFAULT_WORKSPACE_ROOT / sid).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        run_id=rid,
        session_id=sid,
        output_dir=odir,
        trace_jsonl=odir / "trace.jsonl",
        plan_md=odir / "plan.md",
        designs_dir=designs,
        workspace=workspace,
    )


@dataclass
class RunSummary:
    """What we return to the caller after the agent loop finishes."""

    run_id: str
    session_id: str
    output_dir: Path
    num_turns: int = 0
    num_tool_calls: int = 0
    num_tool_errors: int = 0
    total_cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    elapsed_wall_s: float = 0.0
    final_text: str = ""
    failure_reason: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def _content_text(content: Any) -> str:
    """Flatten an MCP-style tool result content list into a text string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                bits.append(str(item.get("text", "")))
            else:
                bits.append(str(item))
        return "".join(bits)
    return str(content)


def _is_tool_error(content: Any) -> bool:
    """Best-effort detection of a tool-result-envelope-with-error."""
    text = _content_text(content)
    return '"error"' in text and '"summary": "Error' in text


async def _drive(
    prompt: str,
    paths: RunPaths,
    *,
    model: str,
    max_turns: int,
    extra_system_prompt: str,
    on_stream_chunk: Optional[Any] = None,
    router: Optional[ComputeRouter] = None,
    skip_debug_tools: bool = True,
    db_path: Optional[Path] = None,
) -> RunSummary:
    """The actual async driver. ``run_campaign`` wraps this with asyncio.run."""
    mcp_server = build_mcp_server(
        router=router,
        skip_debug=skip_debug_tools,
        session_id=paths.session_id,
        host_workspace=paths.workspace,
    )
    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": extra_system_prompt,
        },
        mcp_servers={MCP_SERVER_NAME: mcp_server},
        allowed_tools=[allowed_tool_glob()],
        # bypassPermissions skips per-tool approval prompts, but the
        # built-in Bash/Read/Write/etc tools still execute unless we
        # explicitly disallow them. The skill file says "never use
        # built-ins"; enforce that at the infrastructure layer so the
        # agent can't go off-script. A real E2E surfaced this — the
        # agent reached for Bash to inspect a PDB when data.pdb_fetch
        # didn't surface the info (residue gap detection) it wanted.
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "NotebookEdit",
            "WebFetch", "WebSearch", "Task", "Agent",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,
        # Pin the working dir so any file paths the agent emits resolve
        # under the run's output dir (rather than CWD-at-launch).
        cwd=str(paths.output_dir),
    )

    summary = RunSummary(
        run_id=paths.run_id,
        session_id=paths.session_id,
        output_dir=paths.output_dir,
    )
    t0 = time.monotonic()

    # SQLite handle — kept open for the run so each step write is fast.
    # Errors here must not crash the campaign; persistence is observability,
    # not a correctness gate.
    db_conn = None
    try:
        db_conn = db.open_db(db_path) if db_path else db.open_db()
    except Exception:  # noqa: BLE001
        db_conn = None
    if db_conn is not None:
        try:
            db.record_run_start(
                db_conn,
                run_id=paths.run_id,
                session_id=paths.session_id,
                prompt=prompt,
                output_dir=str(paths.output_dir),
                agent_model=model,
            )
        except Exception:  # noqa: BLE001
            pass

    step_idx = 0

    def _db_step(role: str, **kw: Any) -> None:
        nonlocal step_idx
        if db_conn is None:
            return
        try:
            db.record_step(db_conn, run_id=paths.run_id, step_idx=step_idx, role=role, **kw)
            step_idx += 1
        except Exception:  # noqa: BLE001
            pass

    with TraceWriter(paths.trace_jsonl) as trace:
        try:
            from claude_agent_sdk import __version__ as sdk_version  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            sdk_version = "unknown"
        trace.run_started(
            run_id=paths.run_id,
            session_id=paths.session_id,
            prompt=prompt,
            output_dir=str(paths.output_dir),
            model=model,
            skill_chars=len(extra_system_prompt),
            sdk_version=sdk_version,
        )
        _db_step("user", content=prompt, tool="(prompt)")

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                trace.assistant_text(block.text)
                                summary.final_text = block.text
                                _db_step("assistant_text", content=block.text)
                                if on_stream_chunk:
                                    on_stream_chunk("text", block.text)
                            elif isinstance(block, ThinkingBlock):
                                trace.thinking(block.thinking)
                                if on_stream_chunk:
                                    on_stream_chunk("thinking", block.thinking)
                            elif isinstance(block, ToolUseBlock):
                                trace.tool_use(
                                    tool_use_id=block.id,
                                    name=block.name,
                                    input=block.input,
                                )
                                summary.num_tool_calls += 1
                                summary.tool_calls.append({
                                    "name": block.name,
                                    "input": block.input,
                                })
                                _db_step(
                                    "tool_use",
                                    tool=block.name,
                                    tool_args=block.input,
                                )
                                if on_stream_chunk:
                                    on_stream_chunk(
                                        "tool_use", f"{block.name}({block.input})"
                                    )
                    elif isinstance(message, UserMessage):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                err = _is_tool_error(block.content)
                                trace.tool_result(
                                    tool_use_id=block.tool_use_id,
                                    is_error=err,
                                    content=block.content,
                                )
                                if err:
                                    summary.num_tool_errors += 1
                                _db_step(
                                    "tool_result",
                                    tool_result_summary=_content_text(block.content)[:500],
                                )
                                if on_stream_chunk:
                                    on_stream_chunk(
                                        "tool_result", _content_text(block.content)[:200]
                                    )
                    elif isinstance(message, ResultMessage):
                        summary.num_turns = message.num_turns
                        summary.total_cost_usd = message.total_cost_usd
                        summary.duration_ms = message.duration_ms
                        summary.elapsed_wall_s = time.monotonic() - t0
                        trace.run_completed(
                            session_id=message.session_id,
                            num_turns=message.num_turns,
                            total_cost_usd=message.total_cost_usd,
                            duration_ms=message.duration_ms,
                            elapsed_wall_s=summary.elapsed_wall_s,
                        )
                        if db_conn is not None:
                            try:
                                db.record_run_end(
                                    db_conn,
                                    paths.run_id,
                                    status="completed",
                                    num_designs=0,
                                    total_cost_usd=message.total_cost_usd,
                                    num_turns=message.num_turns,
                                    elapsed_s=summary.elapsed_wall_s,
                                )
                            except Exception:  # noqa: BLE001
                                pass
                    elif isinstance(message, SystemMessage):
                        # SDK lifecycle event — uninteresting for the trace
                        # except as a sanity heartbeat.
                        pass
        except Exception as exc:  # noqa: BLE001 — never crash the CLI
            summary.failure_reason = f"{type(exc).__name__}: {exc}"
            summary.elapsed_wall_s = time.monotonic() - t0
            trace.run_failed(
                error=str(exc), exception_type=type(exc).__name__
            )
            if db_conn is not None:
                try:
                    db.record_run_end(
                        db_conn,
                        paths.run_id,
                        status="failed",
                        num_designs=0,
                        elapsed_s=summary.elapsed_wall_s,
                        failure_reason=summary.failure_reason,
                    )
                except Exception:  # noqa: BLE001
                    pass
    # Post-run triage + report. Failures here are non-fatal — the trace
    # and run dir already contain everything needed to rerun triage later
    # via a separate command.
    try:
        _triage_and_report(paths, prompt, summary, db_conn=db_conn)
    except Exception as exc:  # noqa: BLE001
        # Best-effort log into the trace (the writer is closed by now, so
        # use a small append).
        try:
            with paths.trace_jsonl.open("a", encoding="utf-8") as f:
                import json as _j
                f.write(_j.dumps({"type": "triage_failed", "error": str(exc)}) + "\n")
        except Exception:  # noqa: BLE001
            pass

    if db_conn is not None:
        try:
            db_conn.close()
        except Exception:  # noqa: BLE001
            pass

    return summary


def _triage_and_report(
    paths: RunPaths,
    prompt: str,
    summary: "RunSummary",
    *,
    db_conn=None,
) -> None:
    """Parse trace → write result.json + report.html + populate db.designs."""
    # Lazy import to avoid a top-level cycle (triage.py uses no SDK; report.py
    # is heavy templating; keep them out of the hot agent path until needed).
    from proteinclaw import db
    from proteinclaw.agent.triage import (
        parse_trace,
        stage_ranked_designs,
        write_result_json,
    )
    from proteinclaw.report import render_report

    if not paths.trace_jsonl.exists():
        return
    triage = parse_trace(paths.trace_jsonl)
    stage_ranked_designs(triage, paths.designs_dir)
    write_result_json(triage, paths.output_dir / "result.json")

    render_report(
        triage,
        run_id=paths.run_id,
        prompt=prompt,
        output_path=paths.output_dir / "report.html",
        extra_meta={
            "total_cost_usd": summary.total_cost_usd,
            "elapsed_s": summary.elapsed_wall_s,
            "num_turns": summary.num_turns,
        },
    )

    # Populate db.designs and update the run's target metadata.
    if db_conn is not None:
        try:
            for d in triage.ranked_designs:
                db.record_design(
                    db_conn,
                    run_id=paths.run_id,
                    rank=d.rank or 0,
                    plddt_esm_monomer=d.esm_monomer_plddt,
                    plddt_af2_complex=d.af2_complex_plddt,
                    pdb_path=d.af2_complex_pdb,
                    sequence=d.sequence,
                )
            # Update run with target metadata + final design count.
            tgt = triage.target
            db.record_run_end(
                db_conn,
                paths.run_id,
                status="completed",
                num_designs=len(triage.ranked_designs),
                total_cost_usd=summary.total_cost_usd,
                num_turns=summary.num_turns,
                elapsed_s=summary.elapsed_wall_s,
                target_pdb_id=tgt.pdb_id,
                target_chain=tgt.chain,
                target_crop=tgt.crop,
            )
        except Exception:  # noqa: BLE001
            pass


def _rounds_addendum(rounds: int) -> str:
    """Per-run system-prompt addendum describing the round budget.

    The agent uses this to decide when to call RFD3 a second time with
    refined params after seeing the round-1 ESM/AF2 results. Iteration
    is in-session — no separate process is spawned per round.
    """
    if rounds <= 1:
        return (
            "\n\n---\n## Round budget\n\n"
            "You have **1 round**. Run the pipeline once; do not call RFD3 "
            "more than once. After triage, report final results and stop."
        )
    return (
        f"\n\n---\n## Round budget\n\n"
        f"You have **{rounds} rounds**. In each round, run RFD3 → MPNN → "
        "ESMFold → AF2-multimer, then briefly inspect the rank table. After "
        "round 1, if you would like a refinement round, call RFD3 again with "
        "ONE of these adjustments: (a) narrower binder length window, (b) "
        "more focused hotspots based on the best round-1 binder's interface, "
        "(c) different `sampling_temp` for MPNN (0.2–0.3 for diversity, "
        "0.05–0.1 for high confidence). Log your decision and rationale "
        "before calling RFD3 again. **Total RFD3 calls ≤ {rounds}.** If "
        "round-1 produces a clear winner (complex pLDDT ≥ 85), you may "
        "skip refinement and stop early — log why."
    )


def run_campaign(
    prompt: str,
    *,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    rounds: int = 1,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    skill_path: Optional[Path] = None,
    on_stream_chunk: Optional[Any] = None,
    router: Optional[ComputeRouter] = None,
    skip_debug_tools: bool = True,
    db_path: Optional[Path] = None,
) -> RunSummary:
    """Synchronous wrapper that runs one design campaign end to end.

    Assembles the skill-prompt + per-run rounds addendum, mints the
    on-disk layout, runs the SDK loop, runs triage + report, returns a
    ``RunSummary``. Errors during the loop are captured in the summary
    (``failure_reason``) rather than re-raised.
    """
    if rounds < 1:
        raise ValueError(f"rounds must be ≥ 1, got {rounds!r}")
    skill_text = load_skill_text(skill_path) if skill_path else load_skill_text()
    full_system = skill_text + _rounds_addendum(rounds)
    # Scale the turn cap by rounds — each round needs ~30-40 turns end to end.
    effective_max_turns = max(max_turns, max_turns * rounds // max(1, 1))
    if rounds > 1:
        effective_max_turns = max_turns * rounds

    paths = mint_run_paths(output_dir, run_id=run_id, session_id=session_id)
    paths.plan_md.write_text(
        "# Plan\n\n"
        "The Claude agent's initial plan and reflections during this run.\n"
        "(This file is written incrementally by Phase 6 triage; for now it\n"
        "is a placeholder so the run-output layout is complete.)\n",
        encoding="utf-8",
    )
    summary = asyncio.run(
        _drive(
            prompt,
            paths,
            model=model,
            max_turns=effective_max_turns,
            extra_system_prompt=full_system,
            on_stream_chunk=on_stream_chunk,
            router=router,
            skip_debug_tools=skip_debug_tools,
            db_path=db_path,
        )
    )
    return summary


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_MAX_TURNS",
    "RunPaths",
    "RunSummary",
    "mint_run_paths",
    "run_campaign",
]

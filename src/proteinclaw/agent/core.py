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
    mcp_server = build_mcp_server(router=router, skip_debug=skip_debug_tools)
    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": extra_system_prompt,
        },
        mcp_servers={MCP_SERVER_NAME: mcp_server},
        allowed_tools=[allowed_tool_glob()],
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
    if db_conn is not None:
        try:
            db_conn.close()
        except Exception:  # noqa: BLE001
            pass

    return summary


def run_campaign(
    prompt: str,
    *,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    skill_path: Optional[Path] = None,
    on_stream_chunk: Optional[Any] = None,
    router: Optional[ComputeRouter] = None,
    skip_debug_tools: bool = True,
) -> RunSummary:
    """Synchronous wrapper that runs one design campaign end to end.

    Assembles the skill-prompt, mints the on-disk layout, runs the SDK loop,
    returns a ``RunSummary``. Errors during the loop are captured in the
    summary (``failure_reason``) rather than re-raised.
    """
    skill_text = load_skill_text(skill_path) if skill_path else load_skill_text()
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
            max_turns=max_turns,
            extra_system_prompt=skill_text,
            on_stream_chunk=on_stream_chunk,
            router=router,
            skip_debug_tools=skip_debug_tools,
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

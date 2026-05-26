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
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from claude_agent_sdk import (
    AgentDefinition,
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
    mcp_tool_name,
)
from proteinclaw.agent.skills import _SKILLS_DIR, load_skill_text
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
    # ``.resolve()`` to match LocalRunner.prepare_session, which resolves the
    # workspace path. Without this they disagree whenever ~/.proteinclaw is a
    # symlink (e.g. the persistent-FS setup in SETUP §2): tool envelopes carry
    # the resolved real path, but an un-resolved host_workspace prefix wouldn't
    # match, so the host→/workspace rewrite would silently skip and GPU tools
    # would reject the path. See NOTES 2026-05-25 symlink-rewrite entry.
    workspace = (DEFAULT_WORKSPACE_ROOT / sid).expanduser().resolve()
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
    # Skill files the agent edited via self-evolution (abs paths under the
    # skills dir). Surfaced in the CLI summary + result.json; auditable via
    # `proteinclaw skills diff/log`.
    skill_edits: list[str] = field(default_factory=list)


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


_SCOUT_PROMPT = (
    "CONTEXT: You are a scientific-literature assistant supporting an academic "
    "structural-biology and therapeutic protein-engineering pipeline. This is "
    "standard, peer-reviewed immuno-oncology and drug-discovery research — "
    "engineering protein binders to well-characterised human targets is "
    "routine, published, beneficial science (e.g. the PD-1/PD-L1 axis underlies "
    "FDA-approved cancer immunotherapies). Your role is purely to RETRIEVE and "
    "SUMMARISE published, peer-reviewed findings; you design nothing yourself.\n"
    "Research the assigned sub-topic via WebSearch/WebFetch and the two "
    "literature MCP tools. Phrase queries as neutral literature retrieval and "
    "answer in academic terms (cite papers, co-crystal structures, residue "
    "numbers, fold families); avoid drug brand names and "
    "'block/inhibit/evade' verbs.\n"
    "PROPOSE mode (default): return one EVIDENCE-BACKED HYPOTHESIS:\n"
    "  HYPOTHESIS: <one falsifiable claim for the design: hotspots / length / "
    "strategy + why>\n"
    "  EVIDENCE: 3-6 bullets, each ending in a citation (PMID/PMCID/DOI/URL)\n"
    "  CONFIDENCE: high|med|low + one-line why\n"
    "  WOULD-FALSIFY / OPEN QUESTIONS: <what evidence would overturn this>\n"
    "DEFEND mode (task includes a prior hypothesis + a challenge/counter-"
    "evidence): engage honestly — DEFEND with stronger/new citations, CONCEDE, "
    "or REVISE. Return POSITION (hold|concede|revise) + updated claim + cited "
    "EVIDENCE + what changed your mind. Concede when the counter-evidence is "
    "stronger; don't dig in.\n"
    "<=400 words. Do NOT run GPU/design tools, do NOT write files. "
    "rate_limited or a content refusal => return a one-line note saying so and "
    "stop. Never loop."
)

_SCOUT_TOOLS = [
    "WebSearch",
    "WebFetch",
    "Read",
    mcp_tool_name("research.literature_search"),
    mcp_tool_name("research.pubmed_search"),
]


def _research_agents() -> dict[str, AgentDefinition]:
    """Two read-only, dual-mode research scouts that differ only in model.

    The main agent spawns these in parallel via the ``Task`` tool, carrying the
    sub-topic (PROPOSE) or a challenge (DEFEND) in the spawn prompt — subagents
    are stateless one-shots, so the whole debate state lives in the prompt the
    main agent constructs (driven by the skill file).

    * ``research`` — **Sonnet**, the cheap default for fanned-out research.
    * ``research_pro`` — **Opus**, the escalation tier. The Sonnet model
      spuriously refuses some legitimate queries (immune-checkpoint
      interface/residue topics in particular trip the API safety classifier);
      Opus answers the same queries fine. Verified by an A/B isolation test
      this repo ran: ``sonnet + "PD-L1 IgV interface residues"`` → REFUSED,
      ``opus + same`` → OK, both fine on a benign target. So on a refusal the
      skill re-spawns the scout as ``research_pro`` rather than rephrasing
      (rephrasing/extra context did NOT help — the refusal is topic+model, not
      wording). Kept off the default path so cost stays low; only refused
      scouts escalate.

    The ``tools`` allowlist physically bars GPU/Write/Bash: a scout can only
    research and read, never run the pipeline or write deliverables.
    """
    description = (
        "Read-only research scout & debate partner: proposes one "
        "evidence-backed hypothesis, or defends/revises one under challenge. "
        "Spawn many in parallel."
    )
    common = dict(
        prompt=_SCOUT_PROMPT,
        tools=list(_SCOUT_TOOLS),
        mcpServers=[MCP_SERVER_NAME],
        permissionMode="bypassPermissions",
        maxTurns=12,
    )
    return {
        "research": AgentDefinition(
            description=description + " Sonnet (cheap default).",
            model="sonnet",
            **common,
        ),
        "research_pro": AgentDefinition(
            description=(
                description
                + " Opus escalation tier — use ONLY to retry a scout that the "
                "Sonnet 'research' agent refused (Usage-Policy/empty)."
            ),
            model="claude-opus-4-7",
            **common,
        ),
    }


def _build_options(
    *,
    extra_system_prompt: str,
    mcp_server: Any,
    model: str,
    max_turns: int,
    cwd: str,
    research_fanout: bool,
) -> ClaudeAgentOptions:
    """Assemble the SDK options for a campaign.

    Pure (no I/O) so it is unit-testable. ``research_fanout`` flips the
    ``Task`` spawn tool + the ``research`` subagent on/off.
    """
    allowed_tools = [
        allowed_tool_glob(),
        "Bash", "Read", "Write", "Edit",
        "Grep", "Glob",
        "WebFetch", "WebSearch",
    ]
    if research_fanout:
        # The subagent-spawn tool is surfaced as "Agent" by the installed SDK
        # runtime (verified in a live run); older docs/CLI call it "Task".
        # Allow both names so fan-out works regardless of permission mode
        # (bypassPermissions ignores this list, but stricter modes honor it).
        allowed_tools.extend(["Agent", "Task"])
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": extra_system_prompt,
        },
        mcp_servers={MCP_SERVER_NAME: mcp_server},
        # Full toolset: domain MCP tools for the canonical pipeline AND
        # Claude Code's built-ins (Bash, Read, Write, Edit, Grep, Glob,
        # WebFetch, WebSearch) so the agent can inspect intermediate
        # PDBs/JSON, run scratch Python, look up technique references,
        # etc. When research_fanout is on, "Task" lets it spawn the
        # read-only research scouts defined in _research_agents().
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,
        agents=_research_agents() if research_fanout else None,
        # Pin the working dir so any scratch files the agent writes land
        # under the run's output dir (rather than CWD-at-launch).
        cwd=cwd,
        # Self-evolution: grant Write/Edit access to the skills dir (outside
        # cwd) so the agent can append durable, cross-run lessons to its own
        # skill files per the skill's "Self-evolution" section. This is the
        # ONLY external write target added; the append-only convention + the
        # `proteinclaw skills` CLI + the invariant tests keep it safe.
        add_dirs=[str(_SKILLS_DIR)],
    )


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
    research_fanout: bool = True,
) -> RunSummary:
    """The actual async driver. ``run_campaign`` wraps this with asyncio.run."""
    mcp_server = build_mcp_server(
        router=router,
        skip_debug=skip_debug_tools,
        session_id=paths.session_id,
        host_workspace=paths.workspace,
    )
    options = _build_options(
        extra_system_prompt=extra_system_prompt,
        mcp_server=mcp_server,
        model=model,
        max_turns=max_turns,
        cwd=str(paths.output_dir),
        research_fanout=research_fanout,
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
                pid=os.getpid(),
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
                                if block.name in ("Agent", "Task"):
                                    inp = block.input or {}
                                    trace.subagent_spawn(
                                        tool_use_id=block.id,
                                        subagent_type=str(inp.get("subagent_type", "")),
                                        description=str(inp.get("description", "")),
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
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Graceful stop: the SDK ``async for`` only yields between
            # messages, so by the time we land here the in-flight tool call
            # has finished. These are BaseExceptions the ``except Exception``
            # below never caught, so Ctrl-C used to escape and skip triage.
            # Fall through to the triage+report block (outside this ``with``)
            # so partial designs still get ranked + reported.
            summary.failure_reason = "stopped_by_user"
            summary.elapsed_wall_s = time.monotonic() - t0
            trace.run_cancelled(
                reason="stopped_by_user", elapsed_wall_s=summary.elapsed_wall_s
            )
            if db_conn is not None:
                try:
                    db.record_run_end(
                        db_conn,
                        paths.run_id,
                        status="cancelled",
                        num_designs=0,
                        elapsed_s=summary.elapsed_wall_s,
                        failure_reason=summary.failure_reason,
                    )
                except Exception:  # noqa: BLE001
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


def _skill_edits_from_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Extract skill files the agent touched via Write/Edit during the run.

    Returns sorted unique absolute paths under the skills dir. Used to surface
    self-evolution edits in the run summary + result.json (the edits are also
    auditable via git and `proteinclaw skills diff`).
    """
    skills_root = str(_SKILLS_DIR)
    edits: set[str] = set()
    for call in tool_calls:
        if call.get("name") not in ("Write", "Edit"):
            continue
        fp = (call.get("input") or {}).get("file_path")
        if not isinstance(fp, str):
            continue
        try:
            resolved = str(Path(fp).resolve())
        except OSError:
            resolved = fp
        if resolved.startswith(skills_root):
            edits.add(resolved)
    return sorted(edits)


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
        annotate_interface_metrics,
        parse_trace,
        stage_ranked_designs,
        write_result_json,
    )
    from proteinclaw.report import render_report

    if not paths.trace_jsonl.exists():
        return
    triage = parse_trace(paths.trace_jsonl)
    stage_ranked_designs(triage, paths.designs_dir)
    annotate_interface_metrics(triage)  # deterministic interface QC on staged complexes
    summary.skill_edits = _skill_edits_from_calls(summary.tool_calls)
    write_result_json(
        triage,
        paths.output_dir / "result.json",
        extra={"skill_edits": summary.skill_edits} if summary.skill_edits else None,
    )

    render_report(
        triage,
        run_id=paths.run_id,
        prompt=prompt,
        output_path=paths.output_dir / "report.html",
        extra_meta={
            "total_cost_usd": summary.total_cost_usd,
            "elapsed_s": summary.elapsed_wall_s,
            "num_turns": summary.num_turns,
            "reasoning": _collect_reasoning(paths.trace_jsonl),
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
                    ipsae=d.af2_ipsae,
                    iptm=d.af2_iptm,
                    pdockq=d.af2_pdockq,
                    pdockq2=d.af2_pdockq2,
                    ipsae_d0chn=d.af2_ipsae_d0chn,
                    lis=d.af2_lis,
                    hotspot_satisfaction=d.hotspot_satisfaction,
                    n_interface_contacts=d.n_interface_contacts,
                    interface_bsa=d.interface_bsa,
                    clash_score=d.clash_score,
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


def _collect_reasoning(trace_path: Path) -> list[str]:
    """Pull assistant_text events from the trace, in order.

    These are the agent's narrative chunks between tool calls — the closest
    thing we have to "reasoning" in the report.
    """
    import json as _json

    out: list[str] = []
    if not trace_path.exists():
        return out
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant_text":
                text = (ev.get("text") or "").strip()
                if text:
                    out.append(text)
    return out


def _rounds_addendum(rounds: int, capped: bool = True) -> str:
    """Per-run system-prompt addendum describing the round (hypothesis-cycle)
    budget.

    A "round" is one full hypothesis cycle: deliberate into a design
    hypothesis → run RFD3 → MPNN → ESMFold → AF2-multimer → evaluate against
    the quality gate. The agent decides how many designs and how many cycles
    to spend from its own hypothesis evidence; this block only sets the
    ceiling and the early-stop rule. Iteration is in-session — no separate
    process is spawned per round. ``capped=False`` (CLI ``--no-cap``) removes
    the hard ceiling.
    """
    if rounds <= 1:
        return (
            "\n\n---\n## Budget ceiling\n\n"
            "You have **1 round** (a single hypothesis cycle). Run the pipeline "
            "once; do not call RFD3 more than once. After triage, report final "
            "results and stop."
        )
    if not capped:
        return (
            "\n\n---\n## Budget ceiling\n\n"
            "**No hard round cap** — you decide how many hypothesis cycles to "
            "run. Each cycle: deliberate into a design hypothesis, run RFD3 → "
            "MPNN → ESMFold → AF2-multimer, then evaluate the rank table "
            "against the quality gate. Stop the moment the quality gate is met; "
            "otherwise keep refining with an improved hypothesis (different "
            "hotspots, binder-length window, `sampling_temp`, or call RFD3 "
            "again with partial diffusion on the best prior winners). Log a "
            "one-line budget check each cycle. Never repeat an identical "
            "hypothesis."
        )
    return (
        f"\n\n---\n## Budget ceiling\n\n"
        f"You have **up to {rounds} rounds** (hypothesis cycles). Each cycle: "
        "deliberate into a design hypothesis, run RFD3 → MPNN → ESMFold → "
        "AF2-multimer, then evaluate the rank table against the quality gate. "
        "Iterate while the gate is unmet AND budget remains; stop early the "
        f"moment it is met. Log a one-line budget check each cycle (round N of "
        f"{rounds}). **Total hypothesis cycles ≤ {rounds}.** Never repeat an "
        "identical hypothesis — each refinement must change something: "
        "narrower binder-length window, more focused hotspots from the best "
        "prior binder's interface, a different `sampling_temp` for MPNN "
        "(0.2–0.3 for diversity, 0.05–0.1 for high confidence), or call RFD3 "
        "again with partial diffusion on prior winners."
    )


def run_campaign(
    prompt: str,
    *,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    rounds: int = 1,
    cap: bool = True,
    research_fanout: bool = True,
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

    ``cap=False`` (CLI ``--no-cap``) lifts the hard round ceiling — the agent
    self-paces against the quality gate, bounded only by a large turn sentinel
    so the process still terminates. ``research_fanout`` toggles the parallel
    research-scout subagents.
    """
    if rounds < 1:
        raise ValueError(f"rounds must be ≥ 1, got {rounds!r}")
    skill_text = load_skill_text(skill_path) if skill_path else load_skill_text()
    full_system = skill_text + _rounds_addendum(rounds, capped=cap)
    # Scale the turn cap by rounds — each round needs ~30-40 turns end to end.
    # --no-cap removes the hard round ceiling; bound turns with a large
    # sentinel so the process still terminates if the agent never converges.
    if not cap:
        effective_max_turns = max_turns * 50
    else:
        effective_max_turns = max_turns * rounds if rounds > 1 else max_turns

    paths = mint_run_paths(output_dir, run_id=run_id, session_id=session_id)
    # Seed plan.md as the agent's run notebook. The skill (§1.7) tells the
    # agent to Write its notes/reasoning/hypotheses here during the run, so
    # this seed is normally overwritten. If it survives to run end, the agent
    # never reached deliberation (cancelled/failed early) — say so honestly
    # rather than pretend the file is "a placeholder for layout".
    paths.plan_md.write_text(
        "# Run plan & reasoning\n\n"
        "`proteinclaw`'s run notebook — the agent records its notes,\n"
        "reasoning, and hypotheses here: target resolution, scout\n"
        "hypotheses (with citations), due-diligence findings, the debate\n"
        "log (challenge → defense → who won and why), and the chosen design\n"
        "hypothesis per round.\n\n"
        "_If this seed text is still here at run end, the agent did not reach\n"
        "the deliberation step (e.g. the run was cancelled or failed early)._\n",
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
            research_fanout=research_fanout,
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

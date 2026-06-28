"""Agent-agnostic ProteinClaw MCP server."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool as McpTool

from proteinclaw.agent.mcp_tools import (
    HermesToolSpec,
    _accepts_param,
    _translate_host_path_to_workspace,
    mcp_tool_name,
)
from proteinclaw.agent.run_manager import RunContext, RunManager, context_payload
from proteinclaw.agent.skills import ensure_hermes_skills, hermes_skills_root
from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry as tool_registry


_TOOL_COUNTER = 0
_OBJ_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": True}


def _manager_from_env() -> RunManager:
    runs_dir = os.environ.get("PROTEINCLAW_RUNS_DIR") or os.environ.get("PROTEINCLAW_OUTPUT_DIR") or "./runs"
    workspace_root = os.environ.get("PROTEINCLAW_WORKSPACE_ROOT")
    kwargs: dict[str, Any] = {"runs_dir": Path(runs_dir)}
    if workspace_root:
        kwargs["workspace_root"] = Path(workspace_root)
    return RunManager(**kwargs)


def _next_tool_id() -> str:
    global _TOOL_COUNTER
    _TOOL_COUNTER += 1
    return f"proteinclaw-mcp-{_TOOL_COUNTER}"


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _looks_like_error(result_text: str) -> bool:
    return '"error"' in result_text and (
        '"summary": "Error' in result_text or '"summary":"Error' in result_text
    )


def _error(summary: str, error: str, **extra: Any) -> dict[str, Any]:
    payload = {"summary": summary, "error": error, "metrics": {}}
    payload.update(extra)
    return payload


def _trace(manager: RunManager, ctx: RunContext | None, event: dict[str, Any]) -> None:
    if ctx is not None:
        manager.append_trace(ctx, event)
        return
    trace_path = os.environ.get("PROTEINCLAW_TRACE_JSONL")
    if not trace_path:
        return
    payload = dict(event)
    payload.setdefault("ts", time.time())
    path = Path(trace_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


def _schema_with_run_context(schema: dict[str, Any]) -> dict[str, Any]:
    out = dict(schema or {"type": "object", "properties": {}})
    out["type"] = "object"
    props = dict(out.get("properties") or {})
    props.setdefault("run_id", {"type": "string", "description": "ProteinClaw run id created by proteinclaw_run_create."})
    props.setdefault("session_id", {"type": "string", "description": "Optional session id; defaults to the run's session_id."})
    out["properties"] = props
    required = list(out.get("required") or [])
    if "run_id" not in required:
        required.append("run_id")
    out["required"] = required
    return out


def _context_from_args(manager: RunManager, args: dict[str, Any]) -> RunContext:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    return manager.get_run(run_id)


def _wrap_domain_tool(pc_tool: Any, manager: RunManager, router: ComputeRouter) -> HermesToolSpec:
    name = mcp_tool_name(pc_tool.name)
    description = f"[{pc_tool.name}] {pc_tool.description.strip()}"
    if pc_tool.requires_gpu:
        description += f"\n\nCOMPUTE: requires GPU, min {pc_tool.min_vram_gb} GB VRAM, timeout {pc_tool.timeout_s}s."
    if pc_tool.usage_guide:
        description += f"\n\nUSAGE: {pc_tool.usage_guide.strip()}"

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args or {})
        try:
            ctx = _context_from_args(manager, args)
        except Exception as exc:  # noqa: BLE001
            return _error(f"Error: {exc}", "invalid_run_context")
        call_args = {k: v for k, v in args.items() if k not in {"run_id", "session_id"}}
        session_id = str(args.get("session_id") or ctx.session_id)
        if _accepts_param(pc_tool, "session_id"):
            call_args.setdefault("session_id", session_id)
        if pc_tool.requires_gpu:
            call_args = _translate_host_path_to_workspace(call_args, ctx.workspace)
        result = router.route(pc_tool, **call_args)
        if isinstance(result, dict):
            result.setdefault("run_id", ctx.run_id)
            result.setdefault("session_id", session_id)
        return result

    return HermesToolSpec(
        name=name,
        description=description,
        parameters=_schema_with_run_context(pc_tool.parameters),
        handler=_handler,
    )


def _resolve_under(path: str | Path, root: Path) -> Path:
    root = root.resolve()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"path {p} is outside run directory {root}")
    return p


def _artifact_specs(manager: RunManager) -> list[HermesToolSpec]:
    def _read(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        path = _resolve_under(args.get("path") or args.get("file_path") or "", ctx.output_dir)
        text = path.read_text(encoding="utf-8", errors="replace")
        max_chars = int(args.get("max_chars") or 100_000)
        return {"summary": f"Read {path.relative_to(ctx.output_dir)}", "path": str(path), "text": text[:max_chars], "truncated": len(text) > max_chars}

    def _write(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        path = _resolve_under(args.get("path") or args.get("file_path") or "", ctx.output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = str(args.get("content") or "")
        append = bool(args.get("append") or False)
        with path.open("a" if append else "w", encoding="utf-8") as f:
            f.write(content)
        return {"summary": f"Wrote {path.relative_to(ctx.output_dir)}", "path": str(path), "bytes": len(content.encode("utf-8")), "append": append}

    def _search(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        pattern = str(args.get("pattern") or args.get("query") or "")
        if not pattern:
            return _error("Error: artifact search requires pattern", "invalid_args")
        matches: list[dict[str, Any]] = []
        max_results = int(args.get("max_results") or 50)
        for path in sorted(ctx.output_dir.rglob("*")):
            if not path.is_file():
                continue
            for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pattern in line:
                    matches.append({"path": str(path), "line": idx, "text": line})
                    if len(matches) >= max_results:
                        return {"summary": f"{len(matches)} artifact match(es)", "matches": matches}
        return {"summary": f"{len(matches)} artifact match(es)", "matches": matches}

    schema = _schema_with_run_context(_OBJ_SCHEMA)
    return [
        HermesToolSpec("proteinclaw_artifact_read", "Read a file under a ProteinClaw run directory.", schema, _read),
        HermesToolSpec("proteinclaw_artifact_write", "Write a file under a ProteinClaw run directory.", schema, _write),
        HermesToolSpec("proteinclaw_artifact_search", "Search text files under a ProteinClaw run directory.", schema, _search),
    ]


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


def _append_plan_section(ctx: RunContext, title: str, payload: dict[str, Any]) -> None:
    ctx.plan_md.parent.mkdir(parents=True, exist_ok=True)
    with ctx.plan_md.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {title}\n\n")
        f.write(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        f.write("\n")


def _workflow_record_specs(manager: RunManager) -> list[HermesToolSpec]:
    """Record native host-agent research/debate outputs into run artifacts.

    These tools do not browse or spawn subagents. Codex/Claude do that natively,
    then call these scoped recorders so ProteinClaw reports and traces can prove
    the full agent-native workflow happened.
    """

    def _research(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        payload = {
            "type": "research_record",
            "source": str(args.get("source") or "native_web"),
            "query": str(args.get("query") or ""),
            "summary": str(args.get("summary") or ""),
            "citations": args.get("citations") or [],
            "notes": str(args.get("notes") or ""),
            "ts": time.time(),
        }
        if not payload["query"] and not payload["summary"]:
            return _error("Error: research record requires query or summary", "invalid_args")
        _append_jsonl(ctx.output_dir / "research.jsonl", payload)
        _append_plan_section(ctx, "Native Research Record", payload)
        manager.append_trace(ctx, payload)
        return {
            "summary": "Recorded native web/research evidence for this ProteinClaw run",
            "run_id": ctx.run_id,
            "path": str(ctx.output_dir / "research.jsonl"),
            "metrics": {"num_citations": len(payload["citations"]) if isinstance(payload["citations"], list) else 0},
        }

    def _debate(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        payload = {
            "type": "debate_record",
            "subagent_type": str(args.get("subagent_type") or "native_subagent"),
            "prompt": str(args.get("prompt") or ""),
            "position": str(args.get("position") or ""),
            "summary": str(args.get("summary") or ""),
            "evidence": args.get("evidence") or [],
            "decision": str(args.get("decision") or ""),
            "ts": time.time(),
        }
        if not payload["prompt"] and not payload["summary"]:
            return _error("Error: debate record requires prompt or summary", "invalid_args")
        _append_jsonl(ctx.output_dir / "debate.jsonl", payload)
        _append_plan_section(ctx, "Native Debate Record", payload)
        manager.append_trace(ctx, payload)
        return {
            "summary": "Recorded native subagent/debate output for this ProteinClaw run",
            "run_id": ctx.run_id,
            "path": str(ctx.output_dir / "debate.jsonl"),
            "metrics": {"num_evidence": len(payload["evidence"]) if isinstance(payload["evidence"], list) else 0},
        }

    schema = _schema_with_run_context(_OBJ_SCHEMA)
    return [
        HermesToolSpec(
            "proteinclaw_research_record",
            "Record evidence gathered with native Codex/Claude web or research tools into the active ProteinClaw run.",
            schema,
            _research,
        ),
        HermesToolSpec(
            "proteinclaw_debate_record",
            "Record native Codex/Claude subagent critique, defense, or adjudication into the active ProteinClaw run.",
            schema,
            _debate,
        ),
    ]


def _skill_file(name: str, *, must_exist: bool = True) -> Path:
    root = ensure_hermes_skills()
    skill = (name or "").strip().strip("/")
    if not skill.startswith("proteinclaw-") or "/" in skill or "\\" in skill or not skill:
        raise ValueError("skill must be one ProteinClaw skill directory name")
    path = (root / skill / "SKILL.md").resolve()
    root_resolved = hermes_skills_root().resolve()
    if path != root_resolved and root_resolved not in path.parents:
        raise ValueError("skill path escapes ProteinClaw skill root")
    if must_exist and not path.exists():
        raise FileNotFoundError(f"ProteinClaw skill {skill!r} does not exist")
    return path


def _skill_specs() -> list[HermesToolSpec]:
    def _list(_args: dict[str, Any]) -> dict[str, Any]:
        root = ensure_hermes_skills()
        skills = [p.parent.name for p in sorted(root.glob("*/SKILL.md"))]
        return {"summary": f"{len(skills)} ProteinClaw skill(s)", "skills_root": str(root), "skills": skills, "metrics": {"num_skills": len(skills)}}

    def _read(args: dict[str, Any]) -> dict[str, Any]:
        path = _skill_file(str(args.get("skill") or args.get("name") or ""))
        text = path.read_text(encoding="utf-8", errors="replace")
        max_chars = int(args.get("max_chars") or 20000)
        return {"summary": f"Read ProteinClaw skill {path.parent.name}", "skill": path.parent.name, "path": str(path), "content": text[:max_chars], "truncated": len(text) > max_chars}

    def _append(args: dict[str, Any]) -> dict[str, Any]:
        path = _skill_file(str(args.get("skill") or args.get("name") or ""))
        content = str(args.get("content") or args.get("text") or "").strip()
        if not content:
            return _error("Error: skill append requires content", "invalid_args")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n" + content + "\n")
        return {"summary": f"Appended ProteinClaw skill {path.parent.name}", "skill": path.parent.name, "path": str(path)}

    def _create(args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("skill") or args.get("name") or "")
        path = _skill_file(name, must_exist=False)
        if path.exists():
            return _error(f"Error: ProteinClaw skill {path.parent.name} already exists", "skill_exists")
        content = str(args.get("content") or "").strip() or f"---\nname: {path.parent.name}\ndescription: ProteinClaw learned skill.\n---\n\n# {path.parent.name}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")
        return {"summary": f"Created ProteinClaw skill {path.parent.name}", "skill": path.parent.name, "path": str(path)}

    return [
        HermesToolSpec("proteinclaw_skill_list", "List ProteinClaw skills available to the agent.", {"type": "object", "properties": {}}, _list),
        HermesToolSpec("proteinclaw_skill_read", "Read a ProteinClaw skill by skill directory name.", _OBJ_SCHEMA, _read),
        HermesToolSpec("proteinclaw_skill_append", "Append a durable learned note to a ProteinClaw skill.", _OBJ_SCHEMA, _append),
        HermesToolSpec("proteinclaw_skill_create", "Create a new ProteinClaw skill under the ProteinClaw skill namespace.", _OBJ_SCHEMA, _create),
    ]


def _lifecycle_specs(manager: RunManager) -> list[HermesToolSpec]:
    def _create(args: dict[str, Any]) -> dict[str, Any]:
        ctx = manager.create_run(
            prompt=str(args.get("prompt") or ""),
            run_id=str(args["run_id"]) if args.get("run_id") else None,
            session_id=str(args["session_id"]) if args.get("session_id") else None,
        )
        return {"summary": f"Created ProteinClaw run {ctx.run_id}", **context_payload(ctx)}

    def _status(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        return {"summary": f"ProteinClaw run {ctx.run_id} is {ctx.status}", **context_payload(ctx)}

    def _list(args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 50)
        runs = [context_payload(ctx) for ctx in manager.list_runs(limit=limit)]
        return {"summary": f"{len(runs)} ProteinClaw run(s)", "runs": runs, "metrics": {"num_runs": len(runs)}}

    def _resume(args: dict[str, Any]) -> dict[str, Any]:
        ctx = manager.resume_run(str(args.get("run_id") or ""))
        return {"summary": f"Resumed ProteinClaw run {ctx.run_id}", **context_payload(ctx)}

    def _finalize(args: dict[str, Any]) -> dict[str, Any]:
        ctx = manager.finalize_run(str(args.get("run_id") or ""), status=str(args.get("status") or "completed"))
        return {"summary": f"Finalized ProteinClaw run {ctx.run_id} as {ctx.status}", **context_payload(ctx)}

    return [
        HermesToolSpec("proteinclaw_run_create", "Create a ProteinClaw run/session and workspace.", _OBJ_SCHEMA, _create),
        HermesToolSpec("proteinclaw_run_status", "Return status and paths for a ProteinClaw run.", _schema_with_run_context(_OBJ_SCHEMA), _status),
        HermesToolSpec("proteinclaw_run_list", "List ProteinClaw runs known to this MCP server.", _OBJ_SCHEMA, _list),
        HermesToolSpec("proteinclaw_run_resume", "Mark an existing ProteinClaw run as running and return its context.", _schema_with_run_context(_OBJ_SCHEMA), _resume),
        HermesToolSpec("proteinclaw_run_finalize", "Finalize a ProteinClaw run with a terminal status.", _schema_with_run_context(_OBJ_SCHEMA), _finalize),
    ]


def _report_spec(manager: RunManager) -> HermesToolSpec:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_args(manager, args)
        from proteinclaw.agent.core import (
            _collect_activity,
            _collect_reasoning,
            _collect_trace_events,
            _read_plan_md,
        )
        from proteinclaw.agent.triage import (
            annotate_interface_metrics,
            parse_trace,
            stage_ranked_designs,
            write_result_json,
        )
        from proteinclaw.report import render_report

        triage = parse_trace(ctx.trace_jsonl)
        stage_ranked_designs(triage, ctx.designs_dir)
        annotate_interface_metrics(triage)
        write_result_json(triage, ctx.output_dir / "result.json")
        report = render_report(
            triage,
            run_id=ctx.run_id,
            prompt=str(args.get("prompt") or ctx.prompt),
            output_path=ctx.report_html,
            extra_meta={
                "reasoning": _collect_reasoning(ctx.trace_jsonl),
                "activity": _collect_activity(ctx.trace_jsonl),
                "plan_md": _read_plan_md(ctx.plan_md),
                "trace_events": _collect_trace_events(ctx.trace_jsonl),
            },
        )
        return {"summary": f"Generated ProteinClaw report for run {ctx.run_id}", "run_id": ctx.run_id, "report_html": str(report), "result_json": str(ctx.output_dir / "result.json")}

    return HermesToolSpec("proteinclaw_report_generate", "Generate result.json and report.html from a ProteinClaw run trace.", _schema_with_run_context(_OBJ_SCHEMA), _handler)


def _build_specs(manager: RunManager | None = None, *, skip_debug: bool | None = None) -> list[HermesToolSpec]:
    manager = manager or _manager_from_env()
    router = ComputeRouter()
    include_debug = os.environ.get("PROTEINCLAW_SKIP_DEBUG_TOOLS", "1") == "0"
    if skip_debug is not None:
        include_debug = not skip_debug
    specs: list[HermesToolSpec] = []
    specs.extend(_lifecycle_specs(manager))
    for pc_tool in tool_registry.list_tools():
        if pc_tool.category == "debug" and not include_debug:
            continue
        specs.append(_wrap_domain_tool(pc_tool, manager, router))
    specs.extend(_workflow_record_specs(manager))
    specs.extend(_artifact_specs(manager))
    specs.append(_report_spec(manager))
    specs.extend(_skill_specs())
    return specs


def _mcp_tool(spec: HermesToolSpec) -> McpTool:
    return McpTool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.parameters or {"type": "object", "properties": {}},
    )


async def _invoke(spec: HermesToolSpec, args: dict[str, Any]) -> str:
    result = spec.handler(args or {})
    if inspect.isawaitable(result):
        result = await result
    return _to_text(result)


def build_server(manager: RunManager | None = None) -> Server:
    manager = manager or _manager_from_env()
    specs = _build_specs(manager)
    specs_by_name = {spec.name: spec for spec in specs}
    server = Server(
        "proteinclaw",
        version="0.1.0",
        instructions=(
            "ProteinClaw scientific design tools. Create or resume a run first, "
            "then pass run_id to target, design, structure, metrics, artifact, "
            "skill, and report tools. Use your native web/search/subagent tools "
            "for research and debate; ProteinClaw does not expose generic web "
            "or generic subagent tools."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[McpTool]:
        return [_mcp_tool(spec) for spec in specs]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        args = arguments or {}
        ctx = None
        if args.get("run_id"):
            try:
                ctx = manager.get_run(str(args["run_id"]))
            except Exception:  # noqa: BLE001
                ctx = None
        tool_use_id = _next_tool_id()
        _trace(manager, ctx, {"type": "tool_use", "tool_use_id": tool_use_id, "name": name, "input": args, "source": "proteinclaw_mcp"})
        spec = specs_by_name.get(name)
        if spec is None:
            text = _to_text(_error(f"Error: ProteinClaw MCP tool {name!r} is not registered", "unknown_tool"))
            _trace(manager, ctx, {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": text, "source": "proteinclaw_mcp"})
            return [TextContent(type="text", text=text)]
        try:
            text = await _invoke(spec, args)
            is_error = _looks_like_error(text)
        except Exception as exc:  # noqa: BLE001
            text = _to_text(_error(f"Error: ProteinClaw MCP tool {name!r} crashed: {exc}", "tool_exception", exception_type=type(exc).__name__))
            is_error = True
        _trace(manager, ctx, {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": is_error, "content": text, "source": "proteinclaw_mcp"})
        return [TextContent(type="text", text=text)]

    return server


async def amain() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="proteinclaw",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
                instructions=server.instructions,
            ),
        )


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"proteinclaw MCP server error: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = ["_build_specs", "build_server", "main"]

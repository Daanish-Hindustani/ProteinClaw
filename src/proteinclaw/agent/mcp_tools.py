"""Wrap every registered ``Tool`` as an SDK ``@tool`` in one in-process MCP server.

PRD §6.3 + §9.6 + (post-migration) the Claude Agent SDK pattern:
  * Every `proteinclaw.tools.registry` entry becomes one MCP tool.
  * All tools live in a single in-process MCP server so the agent sees a
    flat catalogue (no per-tool process spawn).
  * The wrapper for each tool just calls ``ComputeRouter.route(...)``,
    keeping the GPU vs in-process dispatch decision in one place.

The agent name mapping flattens ``<category>.<tool>`` → ``<category>_<tool>``
(MCP tool names cannot contain ``.``). The SDK then exposes each tool to
the model as ``mcp__proteinclaw_tools__<flattened>`` so
``allowed_tools=["mcp__proteinclaw_tools__*"]`` covers them all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import Tool, registry as default_registry


MCP_SERVER_NAME = "proteinclaw_tools"


def flatten_tool_name(name: str) -> str:
    """``design.proteinmpnn`` → ``design_proteinmpnn`` (MCP-legal)."""
    return name.replace(".", "_").replace("-", "_")


def mcp_tool_name(name: str) -> str:
    """Full agent-visible name: ``mcp__<server>__<flattened>``."""
    return f"mcp__{MCP_SERVER_NAME}__{flatten_tool_name(name)}"


def _translate_host_path_to_workspace(
    value: Any, host_workspace: Optional[Path]
) -> Any:
    """Recursively translate strings under ``<host_workspace>/`` to ``/workspace/``.

    The agent receives host paths from previous tool envelopes (via
    LocalRunner's output translation). When those paths are passed back
    as inputs to GPU tools, they must be in the container's view
    (``/workspace/...``) since that's how the bind mount surfaces them.
    Non-path strings (plain text, sequences) pass through untouched.
    """
    if host_workspace is None:
        return value
    prefix = str(host_workspace).rstrip("/") + "/"
    if isinstance(value, str):
        if value == str(host_workspace).rstrip("/"):
            return "/workspace"
        if value.startswith(prefix):
            return "/workspace/" + value[len(prefix):]
        return value
    if isinstance(value, list):
        return [_translate_host_path_to_workspace(v, host_workspace) for v in value]
    if isinstance(value, dict):
        return {k: _translate_host_path_to_workspace(v, host_workspace) for k, v in value.items()}
    return value


def _accepts_param(pc_tool: Tool, name: str) -> bool:
    """Does this tool's JSON Schema list ``name`` as an accepted property?"""
    props = (pc_tool.parameters or {}).get("properties", {}) or {}
    return name in props


def _wrap_one(
    pc_tool: Tool,
    router: ComputeRouter,
    *,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
) -> SdkMcpTool:
    """Return one SDK ``@tool``-decorated handler bound to ``pc_tool``.

    If ``session_id`` is provided and the tool accepts a ``session_id``
    parameter, we inject the campaign session into every call so all
    tools share one workspace. For GPU tools, we also rewrite any
    host-workspace paths the agent passes back as inputs into their
    ``/workspace/...`` container-view equivalents (the agent may not
    have noticed the difference between host and container paths).
    """
    flat = flatten_tool_name(pc_tool.name)
    description = _description_for_planner(pc_tool)

    @tool(flat, description, pc_tool.parameters)
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        # 1) Inject campaign session_id if the agent didn't supply one and
        #    the tool accepts it. Keeps every tool call on the same workspace.
        if session_id and _accepts_param(pc_tool, "session_id"):
            args.setdefault("session_id", session_id)

        # 2) For GPU tools, rewrite host paths back to /workspace/... so the
        #    container can read them. Plain-Python tools take host paths
        #    directly so leave their args alone.
        if pc_tool.requires_gpu and host_workspace is not None:
            args = _translate_host_path_to_workspace(args, host_workspace)

        try:
            envelope = router.route(pc_tool, **args)
        except Exception as exc:  # noqa: BLE001 — uniform contract
            envelope = {
                "summary": f"Error: SDK wrapper crashed for {pc_tool.name}: {exc}",
                "error": "wrapper_exception",
                "exception_type": type(exc).__name__,
                "metrics": {},
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(envelope, default=str, ensure_ascii=False),
                }
            ]
        }

    return _handler


def _description_for_planner(t: Tool) -> str:
    """Compose the description string the model sees for a tool.

    Includes the canonical name (``design.proteinmpnn``) plus the human
    description plus the GPU compute hint if relevant. The agent uses
    these blurbs to decide when to call which tool.
    """
    parts = [f"[{t.name}] {t.description.strip()}"]
    if t.requires_gpu:
        parts.append(
            f"COMPUTE: requires GPU, min {t.min_vram_gb} GB VRAM, "
            f"timeout {t.timeout_s}s."
        )
    if t.usage_guide:
        parts.append(f"USAGE: {t.usage_guide.strip()}")
    return "\n\n".join(parts)


def build_mcp_server(
    router: Optional[ComputeRouter] = None,
    registry=default_registry,
    *,
    skip_debug: bool = True,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
):
    """Build the in-process MCP server that exposes every registered tool.

    ``skip_debug`` filters out ``debug.*`` tools (e.g. ``debug._smoke``)
    so they don't pollute the agent's tool catalogue. Set False to expose
    them too (useful for SDK-level integration tests).

    ``session_id`` + ``host_workspace``: when set, every wrapped tool
    gets the campaign's session_id injected (if the tool accepts it) and
    GPU tools get host workspace paths rewritten to ``/workspace/...``
    before dispatch. This makes the whole pipeline share one workspace
    without the agent having to thread session_id through every call.
    """
    router = router or ComputeRouter()
    handlers = []
    for pc_tool in registry.list_tools():
        if skip_debug and pc_tool.category == "debug":
            continue
        handlers.append(
            _wrap_one(
                pc_tool,
                router,
                session_id=session_id,
                host_workspace=host_workspace,
            )
        )
    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME, version="0.1.0", tools=handlers
    )


def allowed_tool_glob() -> str:
    """Glob pattern covering all of our MCP tools — for ``allowed_tools``."""
    return f"mcp__{MCP_SERVER_NAME}__*"


__all__ = [
    "MCP_SERVER_NAME",
    "allowed_tool_glob",
    "build_mcp_server",
    "flatten_tool_name",
    "mcp_tool_name",
]

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


def _wrap_one(pc_tool: Tool, router: ComputeRouter) -> SdkMcpTool:
    """Return one SDK ``@tool``-decorated handler bound to ``pc_tool``."""
    flat = flatten_tool_name(pc_tool.name)
    description = _description_for_planner(pc_tool)

    @tool(flat, description, pc_tool.parameters)
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        # ComputeRouter handles plain-Python vs GPU dispatch + structured
        # error envelopes. We just JSON-serialise the envelope back to the
        # model as a text block so it can read fields directly.
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
):
    """Build the in-process MCP server that exposes every registered tool.

    ``skip_debug`` filters out ``debug.*`` tools (e.g. ``debug._smoke``)
    so they don't pollute the agent's tool catalogue. Set False to expose
    them too (useful for SDK-level integration tests).
    """
    router = router or ComputeRouter()
    handlers = []
    for pc_tool in registry.list_tools():
        if skip_debug and pc_tool.category == "debug":
            continue
        handlers.append(_wrap_one(pc_tool, router))
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

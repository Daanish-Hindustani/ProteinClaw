"""Hermes tool registration for ProteinClaw domain tools.

Hermes is the agent harness, but ProteinClaw still owns the tool contract:
registered ``proteinclaw.tools`` entries are exposed under the historical
``mcp__proteinclaw_tools__<category>_<tool>`` names, route through
``ComputeRouter.route(...)``, inject the campaign ``session_id`` when accepted,
rewrite GPU workspace paths to ``/workspace/...``, and return JSON envelopes.

The module keeps the old ``mcp_*`` naming helpers because skills, traces, and
reports use those stable tool names even though the transport is no longer MCP.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import Tool, registry as default_registry


MCP_SERVER_NAME = "proteinclaw_tools"
HERMES_TOOLSET_NAME = "proteinclaw"


@dataclass(frozen=True)
class HermesToolSpec:
    """Small, dependency-light tool descriptor passed to the Hermes adapter.

    ``hermes-agent`` has changed its public registration surface over time, so
    the adapter converts this neutral shape into whatever the installed
    ``AIAgent`` accepts. Tests can also invoke ``handler`` directly without a
    live model runtime.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    toolset: str = HERMES_TOOLSET_NAME

    async def __call__(self, args: dict[str, Any]) -> Any:
        result = self.handler(args)
        if inspect.isawaitable(result):
            return await result
        return result


def flatten_tool_name(name: str) -> str:
    """``design.proteinmpnn`` -> ``design_proteinmpnn``."""
    return name.replace(".", "_").replace("-", "_")


def mcp_tool_name(name: str) -> str:
    """Stable agent-visible name: ``mcp__proteinclaw_tools__<flattened>``."""
    return f"mcp__{MCP_SERVER_NAME}__{flatten_tool_name(name)}"


def _translate_host_path_to_workspace(value: Any, host_workspace: Optional[Path]) -> Any:
    """Recursively translate strings under ``host_workspace`` to ``/workspace``."""
    if host_workspace is None:
        return value
    bases = {str(host_workspace).rstrip("/")}
    try:
        bases.add(str(Path(host_workspace).resolve()).rstrip("/"))
    except OSError:
        pass
    if isinstance(value, str):
        for base in bases:
            if value == base:
                return "/workspace"
            if value.startswith(base + "/"):
                return "/workspace/" + value[len(base) + 1:]
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


def _description_for_planner(t: Tool) -> str:
    parts = [f"[{t.name}] {t.description.strip()}"]
    if t.requires_gpu:
        parts.append(
            f"COMPUTE: requires GPU, min {t.min_vram_gb} GB VRAM, timeout {t.timeout_s}s."
        )
    if t.usage_guide:
        parts.append(f"USAGE: {t.usage_guide.strip()}")
    return "\n\n".join(parts)


def _json_content(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return an MCP-shaped text content block for trace compatibility."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(envelope, default=str, ensure_ascii=False),
            }
        ]
    }


def _wrap_one(
    pc_tool: Tool,
    router: ComputeRouter,
    *,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
) -> HermesToolSpec:
    """Return one Hermes tool bound to a ProteinClaw registry entry."""
    name = mcp_tool_name(pc_tool.name)
    description = _description_for_planner(pc_tool)

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args or {})
        if session_id and _accepts_param(pc_tool, "session_id"):
            args.setdefault("session_id", session_id)
        if pc_tool.requires_gpu and host_workspace is not None:
            args = _translate_host_path_to_workspace(args, host_workspace)
        try:
            envelope = router.route(pc_tool, **args)
        except Exception as exc:  # noqa: BLE001 - uniform tool contract
            envelope = {
                "summary": f"Error: Hermes wrapper crashed for {pc_tool.name}: {exc}",
                "error": "wrapper_exception",
                "exception_type": type(exc).__name__,
                "metrics": {},
            }
        return _json_content(envelope)

    return HermesToolSpec(
        name=name,
        description=description,
        parameters=pc_tool.parameters,
        handler=_handler,
    )


def build_hermes_toolset(
    router: Optional[ComputeRouter] = None,
    registry=default_registry,
    *,
    skip_debug: bool = True,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
) -> dict[str, Any]:
    """Build the ProteinClaw Hermes toolset.

    The returned dict is intentionally simple: ``HermesHarness`` adapts it to
    the installed ``AIAgent`` API, while tests can inspect it directly.
    """
    router = router or ComputeRouter()
    tools: list[HermesToolSpec] = []
    for pc_tool in registry.list_tools():
        if skip_debug and pc_tool.category == "debug":
            continue
        tools.append(
            _wrap_one(
                pc_tool,
                router,
                session_id=session_id,
                host_workspace=host_workspace,
            )
        )
    return {"name": HERMES_TOOLSET_NAME, "tools": tools}


def build_mcp_server(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible alias for older call sites/tests.

    This no longer creates an MCP server; it returns the Hermes toolset with the
    old stable namespace preserved in each tool name.
    """
    return build_hermes_toolset(*args, **kwargs)


def allowed_tool_glob() -> str:
    """Glob pattern covering all historical ProteinClaw tool names."""
    return f"mcp__{MCP_SERVER_NAME}__*"


__all__ = [
    "HERMES_TOOLSET_NAME",
    "HermesToolSpec",
    "MCP_SERVER_NAME",
    "allowed_tool_glob",
    "build_hermes_toolset",
    "build_mcp_server",
    "flatten_tool_name",
    "mcp_tool_name",
]

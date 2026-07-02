"""ProteinClaw domain-tool specs for MCP and plugin integrations.

External agents own planning, web access, subagents, and orchestration.
ProteinClaw owns the scientific tool contract. Each registered
``proteinclaw.tools`` entry is exposed under a stable
``proteinclaw_<category>_<tool>`` name. The handler:

* injects the campaign ``session_id`` when the tool accepts it,
* rewrites host GPU-workspace paths to ``/workspace/...`` for GPU tools,
* routes through ``ComputeRouter.route(...)``, and
* returns the JSON envelope as a dict for MCP transport.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import Tool, registry as default_registry


MCP_SERVER_NAME = "proteinclaw"
PIPELINE_TOOLSET_NAME = "proteinclaw_pipeline"
RETRIEVAL_TOOLSET_NAME = "proteinclaw_retrieval"

# ProteinClaw tool categories that are pure retrieval (no GPU, no mutation) and
# are therefore safe to expose to the read-only research scouts.
_READ_ONLY_CATEGORIES = {"data", "research"}


@dataclass(frozen=True)
class ToolSpec:
    """Neutral, dependency-light MCP tool descriptor."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    toolset: str = PIPELINE_TOOLSET_NAME

    async def __call__(self, args: dict[str, Any]) -> Any:
        result = self.handler(args)
        if inspect.isawaitable(result):
            return await result
        return result

    @property
    def function_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


def flatten_tool_name(name: str) -> str:
    """``design.proteinmpnn`` -> ``design_proteinmpnn``."""
    return name.replace(".", "_").replace("-", "_")


def tool_name(name: str) -> str:
    """Stable agent-visible name: ``proteinclaw_<flattened>``."""
    return f"{MCP_SERVER_NAME}_{flatten_tool_name(name)}"


def allowed_tool_glob() -> str:
    """Glob pattern covering all ProteinClaw MCP tool names."""
    return f"{MCP_SERVER_NAME}_*"


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
        candidates = [value]
        if value.startswith(("/", "~")):
            try:
                candidates.append(str(Path(value).expanduser().resolve()))
            except OSError:
                pass
        for base in bases:
            for candidate in candidates:
                if candidate == base:
                    return "/workspace"
                if candidate.startswith(base + "/"):
                    return "/workspace/" + candidate[len(base) + 1:]
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


def _toolset_for_category(category: str) -> str:
    """Route a ProteinClaw tool to a broad capability bucket."""
    return RETRIEVAL_TOOLSET_NAME if category in _READ_ONLY_CATEGORIES else PIPELINE_TOOLSET_NAME


def _wrap_one(
    pc_tool: Tool,
    router: ComputeRouter,
    *,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
) -> ToolSpec:
    """Return one tool spec bound to a ProteinClaw registry entry.

    The handler returns the JSON envelope dict; MCP transport serializes it.
    """
    name = tool_name(pc_tool.name)
    description = _description_for_planner(pc_tool)

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args or {})
        if session_id and _accepts_param(pc_tool, "session_id"):
            args.setdefault("session_id", session_id)
        if pc_tool.requires_gpu and host_workspace is not None:
            args = _translate_host_path_to_workspace(args, host_workspace)
        try:
            return router.route(pc_tool, **args)
        except Exception as exc:  # noqa: BLE001 - uniform tool contract
            return {
                "summary": f"Error: ProteinClaw tool wrapper crashed for {pc_tool.name}: {exc}",
                "error": "wrapper_exception",
                "exception_type": type(exc).__name__,
                "metrics": {},
            }

    return ToolSpec(
        name=name,
        description=description,
        parameters=pc_tool.parameters,
        handler=_handler,
        toolset=_toolset_for_category(pc_tool.category),
    )


def proteinclaw_tool_specs(
    router: Optional[ComputeRouter] = None,
    registry=default_registry,
    *,
    skip_debug: bool = True,
    session_id: Optional[str] = None,
    host_workspace: Optional[Path] = None,
) -> list[ToolSpec]:
    """Build specs for every registered ProteinClaw domain tool."""
    router = router or ComputeRouter()
    specs: list[ToolSpec] = []
    for pc_tool in registry.list_tools():
        if skip_debug and pc_tool.category == "debug":
            continue
        specs.append(
            _wrap_one(
                pc_tool,
                router,
                session_id=session_id,
                host_workspace=host_workspace,
            )
        )
    return specs


__all__ = [
    "MCP_SERVER_NAME",
    "PIPELINE_TOOLSET_NAME",
    "RETRIEVAL_TOOLSET_NAME",
    "ToolSpec",
    "allowed_tool_glob",
    "flatten_tool_name",
    "tool_name",
    "proteinclaw_tool_specs",
]

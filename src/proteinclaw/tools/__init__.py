"""Tool registry — single source of truth for what the agent can call.

A ``Tool`` is the atomic unit of agent capability (one per registered
function). Tools self-register at import time via ``@registry.register(...)``;
GPU tools are auto-discovered from ``tool.yaml`` files by
``_container_tools.py``.

The registry is intentionally tiny: lookup, listing by category, and a
planner-facing description string assembled into the agent's system prompt.
Anything more belongs in the router (compute decisions) or the agent
(orchestration), not here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import jsonschema

# Tool names are ``<category>.<tool>`` (PRD §9.1: ``design.rfdiffusion3``,
# ``data.uniprot_fetch``, etc.).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z_][a-z0-9_]*$")

# Known GPU profiles (cosmetic hint for the planner; not validated against a
# closed set so new profiles can be introduced without a registry edit).
_KNOWN_GPU_PROFILES = {"small", "medium", "large", "xlarge"}


def _placeholder_raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Sentinel function used for auto-discovered GPU tools.

    The router intercepts GPU tools and dispatches via ``LocalRunner``; the
    registered callable must never be invoked directly. If it ever is, we want
    a loud error rather than silent garbage.
    """
    raise RuntimeError(
        "GPU tool function called directly — dispatch must go through "
        "ComputeRouter.route(). This is a bug in the caller, not the tool."
    )


@dataclass(frozen=True)
class Tool:
    """An agent-callable capability.

    All fields are required so the registry has full information for both
    planner-facing descriptions and runtime dispatch. The dataclass is frozen
    to make tools effectively read-only after registration.
    """

    name: str  # ``<category>.<tool>`` (e.g. ``design.proteinmpnn``)
    display_name: str  # human-readable label
    description: str  # one-paragraph agent-facing description
    category: str  # ``design``, ``structure``, ``data``, ``research``, ``debug``, ...
    parameters: dict[str, Any]  # JSON Schema for kwargs
    function: Callable[..., dict[str, Any]]
    requires_gpu: bool = False
    min_vram_gb: int = 0
    gpu_profile: Optional[str] = None
    docker_image: Optional[str] = None
    timeout_s: int = 60
    usage_guide: Optional[str] = None
    tool_dir: Optional[str] = None  # absolute path to tools/<name>/ for GPU tools

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"tool name {self.name!r} must match '<category>.<tool>' "
                f"(lowercase, dots, underscores, digits)"
            )
        if self.category != self.name.split(".", 1)[0]:
            raise ValueError(
                f"tool name {self.name!r} disagrees with category {self.category!r}"
            )
        # JSON Schema sanity-check — fail at registration, not at first call.
        try:
            jsonschema.Draft202012Validator.check_schema(self.parameters)
        except jsonschema.SchemaError as exc:
            raise ValueError(
                f"tool {self.name!r}: invalid JSON Schema in parameters: {exc.message}"
            ) from exc
        if self.requires_gpu:
            if self.min_vram_gb <= 0:
                raise ValueError(
                    f"tool {self.name!r}: requires_gpu=True but min_vram_gb={self.min_vram_gb}"
                )
            if self.docker_image is None:
                raise ValueError(
                    f"tool {self.name!r}: requires_gpu=True but docker_image is unset"
                )
        if self.gpu_profile is not None and self.gpu_profile not in _KNOWN_GPU_PROFILES:
            # Warning, not error — keep extensibility open for new profiles.
            pass
        if self.timeout_s <= 0:
            raise ValueError(f"tool {self.name!r}: timeout_s must be positive")


class ToolRegistry:
    """In-process registry of tools.

    Not thread-safe by design — registration happens at import time on the
    main thread, and lookups after that are read-only.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # --- registration --------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
        category: str,
        parameters: dict[str, Any],
        requires_gpu: bool = False,
        min_vram_gb: int = 0,
        gpu_profile: Optional[str] = None,
        docker_image: Optional[str] = None,
        timeout_s: int = 60,
        usage_guide: Optional[str] = None,
    ) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        """Decorator that registers a plain-Python tool."""

        def _decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            tool = Tool(
                name=name,
                display_name=display_name,
                description=description,
                category=category,
                parameters=parameters,
                function=fn,
                requires_gpu=requires_gpu,
                min_vram_gb=min_vram_gb,
                gpu_profile=gpu_profile,
                docker_image=docker_image,
                timeout_s=timeout_s,
                usage_guide=usage_guide,
            )
            self._add(tool)
            return fn

        return _decorator

    def register_tool(self, tool: Tool) -> None:
        """Register a pre-built ``Tool`` (used by auto-discovery)."""
        self._add(tool)

    def _add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(
                f"duplicate tool name {tool.name!r} "
                f"(already registered by {self._tools[tool.name].display_name!r})"
            )
        self._tools[tool.name] = tool

    # --- lookup --------------------------------------------------------------

    def get_tool(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"tool {name!r} not registered") from exc

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self, category: Optional[str] = None) -> list[Tool]:
        tools = list(self._tools.values())
        if category is not None:
            tools = [t for t in tools if t.category == category]
        return sorted(tools, key=lambda t: t.name)

    def categories(self) -> list[str]:
        return sorted({t.category for t in self._tools.values()})

    def clear(self) -> None:
        """Test-only escape hatch. Not used in production code."""
        self._tools.clear()

    # --- planner-facing description -----------------------------------------

    def describe_for_planner(self, category: Optional[str] = None) -> str:
        """Render the tool catalogue for the agent's system prompt.

        Includes each tool's name, one-line description, JSON Schema for
        parameters, and (where relevant) GPU hints. Kept deterministic so
        snapshot tests stay stable.
        """
        tools = self.list_tools(category=category)
        if not tools:
            return "(no tools registered)"

        sections: list[str] = []
        for tool in tools:
            schema_block = json.dumps(self._planner_schema(tool.parameters), indent=2)
            gpu_line = ""
            if tool.requires_gpu:
                gpu_line = (
                    f"  - compute: GPU, min {tool.min_vram_gb} GB VRAM, "
                    f"timeout {tool.timeout_s}s\n"
                )
            usage = f"\n  usage: {tool.usage_guide}" if tool.usage_guide else ""
            sections.append(
                f"## {tool.name} — {tool.display_name}\n"
                f"{tool.description.strip()}\n"
                f"{gpu_line}"
                f"  parameters (JSON Schema):\n```json\n{schema_block}\n```"
                f"{usage}"
            )
        return "\n\n".join(sections)

    @staticmethod
    def _planner_schema(schema: dict[str, Any]) -> dict[str, Any]:
        """Strip jsonschema metadata that adds noise to the planner prompt."""
        cleaned = dict(schema)
        cleaned.pop("$schema", None)
        cleaned.pop("$id", None)
        return cleaned

    # --- iteration -----------------------------------------------------------

    def __iter__(self) -> Iterable[Tool]:
        return iter(self.list_tools())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools


# Module-level singleton. Import sites:
#   from proteinclaw.tools import registry
registry = ToolRegistry()


_PLAIN_PYTHON_TOOL_MODULES = (
    "proteinclaw.tools.uniprot",
    "proteinclaw.tools.pdb",
    "proteinclaw.tools.rcsb",
    "proteinclaw.tools.literature",
    "proteinclaw.tools.pubmed",
    "proteinclaw.tools.interface_metrics",
    "proteinclaw.tools.nanobody_library",
    "proteinclaw.tools.gpcr_target",
    "proteinclaw.tools.gpcr_candidate_qc",
    "proteinclaw.tools.binding_affinity",
)


def bootstrap_default_tools() -> None:
    """Auto-discover GPU tools and import plain-Python tools shipped with the package.

    Called at import time so ``from proteinclaw.tools import registry`` always
    sees the bundled tools. Idempotent: re-registration of an already-known
    tool is treated as a no-op (so re-import in test environments doesn't
    explode).
    """
    # Lazy import to avoid a circular dependency: _container_tools imports
    # ``Tool``, ``registry``, ``_placeholder_raise`` from this module.
    from proteinclaw.tools._container_tools import parse_manifest

    pkg_dir = __import__("pathlib").Path(__file__).resolve().parent
    for manifest_path in sorted(pkg_dir.glob("*/tool.yaml")):
        tool = parse_manifest(manifest_path)
        if tool.name in registry:
            continue
        registry.register_tool(tool)

    # Plain-Python tools self-register via @registry.register decorators at
    # import time. Importing them is the trigger.
    import importlib

    for modname in _PLAIN_PYTHON_TOOL_MODULES:
        importlib.import_module(modname)


bootstrap_default_tools()


__all__ = ["Tool", "ToolRegistry", "bootstrap_default_tools", "registry"]

"""Auto-discovery of GPU tools from ``tool.yaml`` files.

Walks ``src/proteinclaw/tools/*/tool.yaml`` (or any directory supplied
explicitly), validates the schema, and registers each tool with the singleton
registry. The registered ``function`` is a placeholder — the router
intercepts GPU tools and dispatches them via ``LocalRunner``.

Failure modes are loud on purpose: a malformed ``tool.yaml`` aborts discovery
with the file path in the message. We never silently skip a tool directory
container entrypoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import jsonschema
import yaml

from proteinclaw.tools import Tool, ToolRegistry, _placeholder_raise, registry as default_registry

# Required top-level keys in tool.yaml. Values are validated below.
_REQUIRED_KEYS = ("name", "display_name", "description", "category", "parameters")


class ToolManifestError(ValueError):
    """Raised when a ``tool.yaml`` is missing required fields or malformed."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ToolManifestError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolManifestError(f"{path}: top-level YAML must be a mapping")
    return data


def _require(manifest: dict[str, Any], key: str, path: Path) -> Any:
    if key not in manifest:
        raise ToolManifestError(f"{path}: missing required key '{key}'")
    return manifest[key]


def parse_manifest(path: Path) -> Tool:
    """Read ``tool.yaml`` at ``path`` and return a constructed ``Tool``.

    Validates structure but does not register. Used by both auto-discovery
    and by tests that want to assert manifest correctness in isolation.
    """
    manifest = _load_yaml(path)

    for key in _REQUIRED_KEYS:
        _require(manifest, key, path)

    parameters = manifest["parameters"]
    if not isinstance(parameters, dict):
        raise ToolManifestError(f"{path}: 'parameters' must be a JSON Schema object")
    try:
        jsonschema.Draft202012Validator.check_schema(parameters)
    except jsonschema.SchemaError as exc:
        raise ToolManifestError(
            f"{path}: invalid JSON Schema in 'parameters': {exc.message}"
        ) from exc

    compute = manifest.get("compute", {}) or {}
    if not isinstance(compute, dict):
        raise ToolManifestError(f"{path}: 'compute' must be a mapping")
    requires_gpu = bool(compute.get("requires_gpu", False))
    min_vram_gb = int(compute.get("min_vram_gb", 0) or 0)
    gpu_profile = compute.get("gpu_profile")

    execution = manifest.get("execution", {}) or {}
    if not isinstance(execution, dict):
        raise ToolManifestError(f"{path}: 'execution' must be a mapping")
    docker_image = execution.get("docker_image")
    timeout_s = int(execution.get("timeout_s", 60) or 60)

    if requires_gpu:
        if min_vram_gb <= 0:
            raise ToolManifestError(
                f"{path}: compute.requires_gpu=true requires compute.min_vram_gb > 0"
            )
        if not docker_image:
            raise ToolManifestError(
                f"{path}: compute.requires_gpu=true requires execution.docker_image"
            )

    usage_guide = manifest.get("usage_guide")

    try:
        tool = Tool(
            name=str(manifest["name"]),
            display_name=str(manifest["display_name"]),
            description=str(manifest["description"]),
            category=str(manifest["category"]),
            parameters=parameters,
            function=_placeholder_raise,
            requires_gpu=requires_gpu,
            min_vram_gb=min_vram_gb,
            gpu_profile=gpu_profile,
            docker_image=docker_image,
            timeout_s=timeout_s,
            usage_guide=usage_guide,
            tool_dir=str(path.parent.resolve()),
        )
    except ValueError as exc:
        # Surface the file path in the error message — the user will be
        # looking at a stack trace and needs to know which manifest broke.
        raise ToolManifestError(f"{path}: {exc}") from exc

    return tool


def discover_tools(
    root: Optional[Path] = None,
    *,
    registry: Optional[ToolRegistry] = None,
) -> list[Tool]:
    """Walk ``root`` for ``tool.yaml`` files and register each discovered tool.

    ``root`` defaults to the ``tools/`` package directory (this module's
    parent). Returns the list of registered tools, for caller convenience.
    """
    if root is None:
        root = Path(__file__).resolve().parent
    if registry is None:
        registry = default_registry

    discovered: list[Tool] = []
    # Sorted for deterministic registration order — important for the
    # planner-prompt snapshot tests.
    for manifest_path in sorted(root.glob("*/tool.yaml")):
        tool = parse_manifest(manifest_path)
        registry.register_tool(tool)
        discovered.append(tool)
    return discovered


__all__ = ["ToolManifestError", "discover_tools", "parse_manifest"]

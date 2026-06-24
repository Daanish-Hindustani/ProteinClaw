"""Hermes wrapper — name flattening, toolset build, stable namespace."""

from __future__ import annotations

from proteinclaw.agent.mcp_tools import (
    HERMES_TOOLSET_NAME,
    MCP_SERVER_NAME,
    allowed_tool_glob,
    build_hermes_toolset,
    build_mcp_server,
    flatten_tool_name,
    mcp_tool_name,
)
from proteinclaw.tools import registry


def test_flatten_replaces_dots() -> None:
    assert flatten_tool_name("design.rfdiffusion3") == "design_rfdiffusion3"
    assert flatten_tool_name("debug._smoke") == "debug__smoke"


def test_mcp_tool_name_has_prefix() -> None:
    assert mcp_tool_name("design.proteinmpnn") == (
        f"mcp__{MCP_SERVER_NAME}__design_proteinmpnn"
    )


def test_allowed_tool_glob_covers_namespace() -> None:
    assert allowed_tool_glob() == f"mcp__{MCP_SERVER_NAME}__*"


def test_toolset_built_skips_debug_by_default() -> None:
    toolset = build_hermes_toolset()
    assert toolset["name"] == HERMES_TOOLSET_NAME
    names = {t.name for t in toolset["tools"]}
    assert not any("debug" in n for n in names)
    assert mcp_tool_name("design.proteinmpnn") in names


def test_build_mcp_server_alias_returns_hermes_toolset() -> None:
    toolset = build_mcp_server(skip_debug=False)
    assert toolset["name"] == HERMES_TOOLSET_NAME
    assert any(t.category == "debug" for t in registry.list_tools())
    assert any("debug" in t.name for t in toolset["tools"])

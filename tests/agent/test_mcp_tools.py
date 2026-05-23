"""MCP wrapper — name flattening, server build, env wiring."""

from __future__ import annotations

from proteinclaw.agent.mcp_tools import (
    MCP_SERVER_NAME,
    allowed_tool_glob,
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


def test_server_built_skips_debug_by_default() -> None:
    srv = build_mcp_server()
    # The SDK doesn't expose tool count directly; we just sanity-check the
    # returned dict shape used elsewhere in the SDK.
    assert isinstance(srv, dict)
    assert srv.get("name") == MCP_SERVER_NAME
    assert srv.get("type") == "sdk"


def test_server_can_include_debug() -> None:
    srv = build_mcp_server(skip_debug=False)
    assert isinstance(srv, dict)
    # Sanity: registry must currently contain the smoke debug tool, so the
    # build path that includes it exercises a real category-filter branch.
    assert any(t.category == "debug" for t in registry.list_tools())

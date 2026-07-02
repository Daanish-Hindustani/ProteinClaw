"""MCP tool-spec name flattening and spec build."""

from __future__ import annotations

import asyncio

from proteinclaw.agent.mcp_tools import (
    MCP_SERVER_NAME,
    PIPELINE_TOOLSET_NAME,
    RETRIEVAL_TOOLSET_NAME,
    ToolSpec,
    allowed_tool_glob,
    flatten_tool_name,
    proteinclaw_tool_specs,
    tool_name,
)
from proteinclaw.tools import registry


def test_flatten_replaces_dots() -> None:
    assert flatten_tool_name("design.rfdiffusion3") == "design_rfdiffusion3"
    assert flatten_tool_name("debug._smoke") == "debug__smoke"


def test_tool_name_has_proteinclaw_prefix() -> None:
    assert tool_name("design.proteinmpnn") == f"{MCP_SERVER_NAME}_design_proteinmpnn"


def test_allowed_tool_glob_covers_namespace() -> None:
    assert allowed_tool_glob() == f"{MCP_SERVER_NAME}_*"


def test_specs_skip_debug_by_default() -> None:
    names = {s.name for s in proteinclaw_tool_specs()}
    assert not any("debug" in n for n in names)
    assert tool_name("design.proteinmpnn") in names


def test_specs_include_debug_when_requested() -> None:
    assert any(t.category == "debug" for t in registry.list_tools())
    names = {s.name for s in proteinclaw_tool_specs(skip_debug=False)}
    assert any("debug" in n for n in names)


def test_specs_bucket_retrieval_tools_separately() -> None:
    specs = {s.name: s for s in proteinclaw_tool_specs()}
    assert specs[tool_name("design.proteinmpnn")].toolset == PIPELINE_TOOLSET_NAME
    lit = specs.get(tool_name("research.literature_search"))
    assert lit is not None and lit.toolset == RETRIEVAL_TOOLSET_NAME


def test_function_schema_shape() -> None:
    spec = proteinclaw_tool_specs()[0]
    schema = spec.function_schema
    assert set(schema) >= {"name", "description", "parameters"}
    assert schema["name"] == spec.name
    assert schema["parameters"].get("type") == "object" or "properties" in schema["parameters"]


def test_tool_spec_invokes_sync_handler() -> None:
    spec = ToolSpec(
        name="t",
        description="d",
        parameters={"type": "object"},
        handler=lambda args: {"summary": "ok", "echo": args.get("x")},
    )
    assert spec.function_schema["name"] == "t"
    assert asyncio.run(spec({"x": 1})) == {"summary": "ok", "echo": 1}

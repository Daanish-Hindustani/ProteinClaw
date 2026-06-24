"""Hermes wrapper — name flattening, spec build, registry registration."""

from __future__ import annotations

import asyncio
import json

from proteinclaw.agent.mcp_tools import (
    HERMES_TOOLSET_NAME,
    MCP_SERVER_NAME,
    RESEARCH_TOOLSET_NAME,
    allowed_tool_glob,
    flatten_tool_name,
    mcp_tool_name,
    proteinclaw_tool_specs,
    register_specs,
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


def test_specs_skip_debug_by_default() -> None:
    names = {s.name for s in proteinclaw_tool_specs()}
    assert not any("debug" in n for n in names)
    assert mcp_tool_name("design.proteinmpnn") in names


def test_specs_include_debug_when_requested() -> None:
    assert any(t.category == "debug" for t in registry.list_tools())
    names = {s.name for s in proteinclaw_tool_specs(skip_debug=False)}
    assert any("debug" in n for n in names)


def test_specs_route_retrieval_tools_to_research_toolset() -> None:
    specs = {s.name: s for s in proteinclaw_tool_specs()}
    # A GPU/design tool -> privileged toolset.
    assert specs[mcp_tool_name("design.proteinmpnn")].toolset == HERMES_TOOLSET_NAME
    # A retrieval tool -> read-only research toolset (scout-safe).
    lit = specs.get(mcp_tool_name("research.literature_search"))
    assert lit is not None and lit.toolset == RESEARCH_TOOLSET_NAME


def test_hermes_schema_is_openai_inner_shape() -> None:
    spec = proteinclaw_tool_specs()[0]
    schema = spec.hermes_schema
    assert set(schema) >= {"name", "description", "parameters"}
    assert schema["name"] == spec.name
    assert schema["parameters"].get("type") == "object" or "properties" in schema["parameters"]


class _FakeRegistry:
    """Minimal stand-in for hermes ``model_tools.registry``."""

    def __init__(self) -> None:
        self.registered: list[dict] = []

    def register(self, **kwargs) -> None:
        self.registered.append(kwargs)


def test_register_specs_registers_into_hermes_registry() -> None:
    fake = _FakeRegistry()
    specs = proteinclaw_tool_specs()
    toolsets = register_specs(fake, specs)

    assert set(toolsets) == {HERMES_TOOLSET_NAME, RESEARCH_TOOLSET_NAME}
    assert len(fake.registered) == len(specs)
    one = fake.registered[0]
    assert one["is_async"] is True
    assert one["override"] is True
    assert one["toolset"] in (HERMES_TOOLSET_NAME, RESEARCH_TOOLSET_NAME)
    assert set(one["schema"]) >= {"name", "description", "parameters"}
    assert callable(one["handler"])


def test_registered_handler_returns_json_string() -> None:
    """The handler hermes calls must return a JSON string, not a dict."""
    from proteinclaw.agent.mcp_tools import HermesToolSpec

    spec = HermesToolSpec(
        name="t",
        description="d",
        parameters={"type": "object"},
        handler=lambda args: {"summary": "ok", "echo": args.get("x")},
    )
    fake = _FakeRegistry()
    register_specs(fake, [spec])
    handler = fake.registered[0]["handler"]
    out = asyncio.run(handler({"x": 1}, session_id="s", task_id="t", user_task="u"))
    assert isinstance(out, str)
    assert json.loads(out) == {"summary": "ok", "echo": 1}

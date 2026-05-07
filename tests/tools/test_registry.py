"""Tests for ToolRegistry — register, lookup, describe_all, invoke, invocation log."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from proteinclaw.tools.base_tool import BaseTool, ToolExecutionError, ToolStatus
from proteinclaw.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
)


class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    n: int


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    n: int


class _Echo(BaseTool):
    name = "echo"
    description = "echoes n"
    input_schema = _In
    output_schema = _Out

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        assert isinstance(inputs, _In)
        return _Out(n=inputs.n)


class _Boom(BaseTool):
    name = "boom"
    description = "always fails"
    input_schema = _In
    output_schema = _Out

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        raise RuntimeError("nope")


def test_register_and_find() -> None:
    reg = ToolRegistry()
    tool = _Echo()
    reg.register(tool)
    assert reg.find_by_name("echo") is tool


def test_duplicate_register_raises() -> None:
    reg = ToolRegistry()
    reg.register(_Echo())
    with pytest.raises(DuplicateToolError):
        reg.register(_Echo())


def test_unknown_lookup_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(UnknownToolError):
        reg.find_by_name("nope")


def test_describe_all_sorted_by_name() -> None:
    reg = ToolRegistry()
    reg.register(_Echo())
    reg.register(_Boom())
    descs = reg.describe_all()
    assert [d.name for d in descs] == ["boom", "echo"]
    # Schemas surface as JSON-Schema dicts.
    for d in descs:
        assert "properties" in d.input_schema
        assert "properties" in d.output_schema


async def test_invoke_records_success() -> None:
    reg = ToolRegistry()
    reg.register(_Echo())
    out = await reg.invoke("echo", {"n": 7})
    assert out.payload == {"n": 7}
    invs = reg.invocations()
    assert len(invs) == 1
    assert invs[0].tool_name == "echo"
    assert invs[0].status == ToolStatus.SUCCESS
    assert invs[0].latency_ms >= 0


async def test_invoke_records_failure_and_reraises() -> None:
    reg = ToolRegistry()
    reg.register(_Boom())
    with pytest.raises(ToolExecutionError):
        await reg.invoke("boom", {"n": 1})
    invs = reg.invocations()
    assert len(invs) == 1
    assert invs[0].status == ToolStatus.FAILURE
    assert invs[0].error is not None


async def test_invoke_unknown_tool_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(UnknownToolError):
        await reg.invoke("ghost", {"n": 1})
    # Unknown-tool calls are not recorded as invocations.
    assert reg.invocations() == ()

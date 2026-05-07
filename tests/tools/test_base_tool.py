"""Tests for BaseTool / ToolOutput / ToolExecutionError."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from proteinclaw.tools.base_tool import (
    BaseTool,
    ToolExecutionError,
    ToolInvocation,
    ToolOutput,
    ToolStatus,
)


class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    n: int


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    doubled: int


class _GoodTool(BaseTool):
    name = "good"
    description = "doubles n"
    input_schema = _In
    output_schema = _Out

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        assert isinstance(inputs, _In)
        return _Out(doubled=inputs.n * 2)


class _Boom(BaseTool):
    name = "boom"
    description = "raises"
    input_schema = _In
    output_schema = _Out

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        raise RuntimeError("backend exploded")


class _WrongShape(BaseTool):
    name = "wrong_shape"
    description = "returns the wrong type"
    input_schema = _In
    output_schema = _Out

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        return _In(n=1)  # not _Out — should be caught


async def test_invoke_success_envelope() -> None:
    out = await _GoodTool().invoke({"n": 21})
    assert out.tool_name == "good"
    assert out.status == ToolStatus.SUCCESS
    assert out.payload == {"doubled": 42}
    assert "latency_ms" in out.metrics
    assert out.metrics["latency_ms"] >= 0


async def test_invoke_input_validation_failure() -> None:
    tool = _GoodTool()
    with pytest.raises(ToolExecutionError) as excinfo:
        await tool.invoke({"n": "not-an-int"})
    assert excinfo.value.tool_name == "good"
    assert "input validation failed" in str(excinfo.value)


async def test_invoke_backend_error_wrapped() -> None:
    tool = _Boom()
    with pytest.raises(ToolExecutionError) as excinfo:
        await tool.invoke({"n": 1})
    assert excinfo.value.tool_name == "boom"
    assert "backend error" in str(excinfo.value)
    # The original RuntimeError must be chained for debuggability.
    assert isinstance(excinfo.value.__cause__, RuntimeError)


async def test_invoke_output_shape_mismatch_raises() -> None:
    tool = _WrongShape()
    with pytest.raises(ToolExecutionError) as excinfo:
        await tool.invoke({"n": 1})
    assert "is not _Out" in str(excinfo.value)


async def test_invoke_extra_input_field_rejected() -> None:
    tool = _GoodTool()
    with pytest.raises(ToolExecutionError):
        await tool.invoke({"n": 1, "extra": "nope"})


def test_tool_output_is_frozen() -> None:
    out = ToolOutput(tool_name="t", status=ToolStatus.SUCCESS, payload={})
    with pytest.raises(ValidationError):
        out.payload = {"mutated": True}  # type: ignore[misc]


def test_tool_invocation_round_trip() -> None:
    inv = ToolInvocation(tool_name="x", latency_ms=12.3, status=ToolStatus.SUCCESS)
    rt = ToolInvocation.model_validate_json(inv.model_dump_json())
    assert rt == inv


def test_tool_execution_error_carries_stderr() -> None:
    err = ToolExecutionError("foo", "bad", stderr="line 1\nline 2")
    assert err.tool_name == "foo"
    assert err.stderr == "line 1\nline 2"
    assert "[foo] bad" in str(err)


# `Any` is imported just to be available for fixture extension; ruff is happy
_ = Any

"""Tests for the SandboxTool registered in the tool registry."""

from __future__ import annotations

import pytest

from proteinclaw.tools.base_tool import ToolExecutionError, ToolStatus
from proteinclaw.tools.sandbox_tool import (
    MAX_CODE_LENGTH,
    MAX_SANDBOX_TIMEOUT,
    SandboxOutputs,
    SandboxTool,
)


async def test_sandbox_runs_simple_snippet() -> None:
    out = await SandboxTool().invoke({"code": "print('hello from sandbox')"})
    assert out.status is ToolStatus.SUCCESS
    parsed = SandboxOutputs.model_validate(out.payload)
    assert parsed.returncode == 0
    assert "hello from sandbox" in parsed.stdout
    assert parsed.timed_out is False


async def test_sandbox_captures_runtime_error_in_stderr() -> None:
    out = await SandboxTool().invoke({"code": "raise RuntimeError('boom')"})
    parsed = SandboxOutputs.model_validate(out.payload)
    assert parsed.returncode != 0
    assert "RuntimeError: boom" in parsed.stderr


async def test_sandbox_rejects_empty_code() -> None:
    with pytest.raises(ToolExecutionError):
        await SandboxTool().invoke({"code": ""})


async def test_sandbox_rejects_code_too_long() -> None:
    huge = "x = 1\n" * (MAX_CODE_LENGTH // 4)
    with pytest.raises(ToolExecutionError):
        await SandboxTool().invoke({"code": huge})


async def test_sandbox_rejects_timeout_over_max() -> None:
    with pytest.raises(ToolExecutionError):
        await SandboxTool().invoke(
            {"code": "print('x')", "timeout_seconds": MAX_SANDBOX_TIMEOUT + 1}
        )


def test_sandbox_registered_in_default_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sandbox tool is part of `build_default_registry()`."""
    from proteinclaw.tools.factory import build_default_registry

    monkeypatch.setenv("PROTEINCLAW_BACKEND", "mock")
    registry = build_default_registry()
    assert "sandbox" in {d.name for d in registry.describe_all()}

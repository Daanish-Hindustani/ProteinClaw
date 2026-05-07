"""Tests for the Python sandbox: success, error, timeout, memory limit, output truncation."""

from __future__ import annotations

import sys

import pytest

from proteinclaw.sandbox.python_runner import PythonRunner, SandboxResult


async def test_success_returns_clean_result() -> None:
    runner = PythonRunner(timeout_seconds=10.0)
    result = await runner.run("print('hello')")
    assert isinstance(result, SandboxResult)
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.runtime_seconds >= 0


async def test_python_error_captured_in_stderr() -> None:
    runner = PythonRunner(timeout_seconds=10.0)
    result = await runner.run("raise RuntimeError('boom')")
    assert result.returncode != 0
    assert "RuntimeError: boom" in result.stderr
    assert result.timed_out is False


async def test_timeout_kills_child() -> None:
    runner = PythonRunner(timeout_seconds=0.5)
    result = await runner.run("import time; time.sleep(5)")
    assert result.timed_out is True
    assert result.returncode != 0  # killed


async def test_output_truncation() -> None:
    runner = PythonRunner(timeout_seconds=10.0, max_output_bytes=100)
    # Produce ~5KB of output to ensure truncation kicks in.
    result = await runner.run("print('x' * 5000)")
    assert "[...truncated at 100 bytes]" in result.stdout
    # Truncated chunk is at most max_output_bytes + the suffix length; the
    # suffix is ~30 chars so total stays small.
    assert len(result.stdout) < 200


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="RLIMIT_AS only reliably enforces on Linux; macOS often ignores it.",
)
async def test_memory_limit_kills_runaway() -> None:
    """A child trying to allocate beyond the cap exits non-zero (Linux only)."""
    runner = PythonRunner(timeout_seconds=15.0, max_memory_mb=64)
    code = "x = bytearray(512 * 1024 * 1024)"  # 512 MB > 64 MB cap
    result = await runner.run(code)
    assert result.returncode != 0


async def test_rlimit_preamble_failures_do_not_crash() -> None:
    """The preamble's setrlimit is wrapped in try/except — child should still run cleanly."""
    runner = PythonRunner(timeout_seconds=10.0, max_memory_mb=4096)
    result = await runner.run("print('still ok')")
    assert result.returncode == 0
    assert result.stdout.strip() == "still ok"


def test_constructor_validates_args() -> None:
    with pytest.raises(ValueError):
        PythonRunner(timeout_seconds=0)
    with pytest.raises(ValueError):
        PythonRunner(max_memory_mb=0)
    with pytest.raises(ValueError):
        PythonRunner(max_output_bytes=0)

"""Shared subprocess primitives for local GPU tool backends."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

from proteinclaw.tools.base_tool import ToolExecutionError


def deterministic_run_id(*parts: str, length: int = 16) -> str:
    """Stable hex id derived from the inputs, identical across processes.

    Python's built-in ``hash()`` for strings is randomized per process
    (via ``PYTHONHASHSEED``), so cache directories keyed on it would
    differ between runs and break idempotent re-runs. SHA-256 truncated
    to ``length`` hex chars gives us a reproducible name without
    introducing dependencies.
    """
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


async def run_subprocess(
    *args: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    tool_name: str,
) -> tuple[str, str]:
    """Run a subprocess and return (stdout, stderr).

    Wraps `asyncio.create_subprocess_exec` with consistent error handling.
    Non-zero exit codes raise `ToolExecutionError` carrying the stderr —
    callers don't need to inspect returncode themselves.

    Args:
        *args: Command and arguments. The first element is the binary.
        cwd: Working directory for the child.
        env: Override environment. Defaults to inheriting the parent's.
        timeout_seconds: Wall-clock cap. None disables.
        tool_name: For error messages — surfaces in `ToolExecutionError`.

    Returns:
        Decoded `(stdout, stderr)` strings.

    Raises:
        ToolExecutionError: On non-zero exit, missing binary, or timeout.
    """
    full_env = {**os.environ, **(env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise ToolExecutionError(tool_name, f"binary not found: {args[0]}") from e
    try:
        if timeout_seconds is not None:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        else:
            stdout_b, stderr_b = await proc.communicate()
    except TimeoutError as e:
        proc.kill()
        await proc.communicate()
        raise ToolExecutionError(tool_name, f"timed out after {timeout_seconds}s") from e

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        # Show the *tail* of stderr — Python tracebacks put the real error
        # on the last line, while the leading lines are framework boilerplate
        # (Hydra banners, deprecation warnings, etc.). Truncating from the
        # head, as the previous 500-char prefix did, routinely hid the
        # actual exception type and message — which then never reached the
        # LLM driving the retry loop. 4000 chars holds 30-50 lines of
        # traceback comfortably.
        snippet = stderr[-4000:] if len(stderr) > 4000 else stderr
        raise ToolExecutionError(
            tool_name,
            f"exit code {proc.returncode}: {snippet}",
            stderr=stderr,
        )
    return stdout, stderr

"""Python sandbox: run untrusted code in a subprocess with resource limits.

Sub-agents need to execute ad-hoc analysis (RMSD computation, PDB parsing,
metric calculation). The sandbox enforces three hard limits:

1. **Wall-clock timeout** via `asyncio.wait_for`.
2. **Address-space limit** via a `resource.setrlimit(RLIMIT_AS, ...)`
   preamble injected into the child's code (POSIX). Best-effort — some
   OSes (notably macOS) silently ignore it.
3. **Output truncation** to keep a runaway `print` loop from blowing
   memory upstream.

The child runs `python -c <preamble + user_code>` with the host
interpreter, in a clean environment derived from the parent. This is a
*trust-boundary* sandbox, not a security one — the threat model is "LLM
wrote a buggy script," not "adversary trying to escape." See
`docs/setup.md` for the deployment threat model.

The earlier implementation used `preexec_fn`. Python 3.14 tightens fork
safety and the preexec path is fragile across platforms; the preamble
approach is portable and equally effective for the trust-boundary model.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_MEMORY_MB = 512
DEFAULT_MAX_OUTPUT_BYTES = 1_000_000

_MB = 1024 * 1024


class SandboxResult(BaseModel):
    """Outcome of one sandbox run.

    Attributes:
        returncode: Process exit code. Negative values are signal terminations.
        stdout: Captured stdout, truncated to `max_output_bytes`.
        stderr: Captured stderr, truncated to `max_output_bytes`.
        runtime_seconds: Wall-clock time elapsed.
        timed_out: True iff the runner killed the child for exceeding the
            wall-clock budget.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str
    runtime_seconds: float = Field(ge=0.0)
    timed_out: bool = False


class PythonRunner:
    """Subprocess-based Python runner with rlimit preamble and timeout enforcement.

    Construct once per session (or even per process) and call `run` per
    snippet. The runner is async-safe — concurrent calls each spawn their
    own child process.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        python_executable: str | None = None,
    ) -> None:
        """Initialize the runner with hard caps.

        Args:
            timeout_seconds: Wall-clock cap; child is killed if exceeded.
            max_memory_mb: Address-space cap in MB. Best-effort; some OSes ignore.
            max_output_bytes: Truncate stdout/stderr to this many bytes.
            python_executable: Override the host interpreter; defaults to
                `sys.executable`. Useful for tests on a pinned Python.
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_memory_mb <= 0:
            raise ValueError("max_memory_mb must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._timeout = timeout_seconds
        self._mem_limit = max_memory_mb * _MB
        self._output_cap = max_output_bytes
        self._python = python_executable or sys.executable

    async def run(self, code: str, *, cwd: Path | None = None) -> SandboxResult:
        """Execute `code` in a fresh subprocess.

        Args:
            code: Python source to run.
            cwd: Optional working directory for the child.

        Returns:
            A `SandboxResult` describing the run. Child errors land in
            `stderr` and `returncode`; this method does not raise on
            child failure.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()

        full_code = self._build_child_program(code)
        proc = await asyncio.create_subprocess_exec(
            self._python,
            "-c",
            full_code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError:
            timed_out = True
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()

        runtime = loop.time() - start
        return SandboxResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=self._truncate(stdout_b),
            stderr=self._truncate(stderr_b),
            runtime_seconds=runtime,
            timed_out=timed_out,
        )

    def _build_child_program(self, user_code: str) -> str:
        """Prepend the rlimit preamble to the user's code.

        The preamble swallows `setrlimit` errors so a permissive OS doesn't
        crash the run; the wall-clock timeout is the load-bearing defense.
        """
        preamble = (
            "import resource as _proteinclaw_resource\n"
            "try:\n"
            f"    _proteinclaw_resource.setrlimit(\n"
            f"        _proteinclaw_resource.RLIMIT_AS,\n"
            f"        ({self._mem_limit}, {self._mem_limit}),\n"
            "    )\n"
            "except (OSError, ValueError):\n"
            "    pass\n"
            "del _proteinclaw_resource\n"
        )
        return preamble + user_code

    def _truncate(self, data: bytes) -> str:
        """Decode and truncate stdout/stderr for the result envelope."""
        if len(data) <= self._output_cap:
            return data.decode("utf-8", errors="replace")
        head = data[: self._output_cap].decode("utf-8", errors="replace")
        return head + f"\n[...truncated at {self._output_cap} bytes]"

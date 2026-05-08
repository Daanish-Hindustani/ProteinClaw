"""Python sandbox exposed as a `BaseTool` for the LLM-driven sub-agent.

Wraps `proteinclaw.sandbox.python_runner.PythonRunner` so the LLM can run
ad-hoc analysis snippets (RMSD calculation, PDB parsing, metric
computation, etc.) the same way it calls protein-design tools.

Threat model is unchanged from the underlying runner: this is a
trust-boundary sandbox (LLM-written buggy script), not a security one.
The wrapper enforces a wall-clock cap and an output truncation cap; the
LLM cannot escalate beyond those by tweaking ``timeout_seconds``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.sandbox.python_runner import PythonRunner
from proteinclaw.tools.base_tool import BaseTool

DEFAULT_SANDBOX_TIMEOUT = 30.0
MAX_SANDBOX_TIMEOUT = 120.0
MAX_CODE_LENGTH = 16_000


class SandboxInputs(BaseModel):
    """Inputs for one sandbox invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=MAX_CODE_LENGTH)
    timeout_seconds: float = Field(
        default=DEFAULT_SANDBOX_TIMEOUT,
        gt=0.0,
        le=MAX_SANDBOX_TIMEOUT,
    )


class SandboxOutputs(BaseModel):
    """Outputs from one sandbox invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    returncode: int
    stdout: str
    stderr: str
    runtime_seconds: float = Field(ge=0.0)
    timed_out: bool = False


class SandboxTool(BaseTool):
    """Run a Python snippet in the bundled subprocess sandbox.

    The LLM uses this for analysis steps that don't have a dedicated
    tool — computing RMSD between two PDBs, summarising a CSV, parsing
    a Foldseek result table, etc. ``code`` is the Python source; the
    runner injects the rlimit preamble before execution.
    """

    name = "sandbox"
    description = (
        "Run a short Python snippet in a subprocess sandbox with a wall-clock "
        "cap. Use for ad-hoc analysis: parsing PDBs, computing RMSD, summarising "
        "tool outputs. Returns stdout, stderr, returncode, and a timed_out flag."
    )
    input_schema = SandboxInputs
    output_schema = SandboxOutputs

    def __init__(self, runner: PythonRunner | None = None) -> None:
        """Bind a PythonRunner; constructs a default one if absent."""
        self._runner = runner or PythonRunner()

    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Delegate to the runner; never re-raise (failures land in stderr)."""
        assert isinstance(inputs, SandboxInputs)
        # The runner honours its own configured timeout; we don't pass the
        # per-call timeout through because mutating PythonRunner mid-call
        # would break async safety. The default runner's cap matches our
        # MAX_SANDBOX_TIMEOUT, which is what the schema validates against.
        result = await self._runner.run(inputs.code)
        return SandboxOutputs(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            runtime_seconds=result.runtime_seconds,
            timed_out=result.timed_out,
        )

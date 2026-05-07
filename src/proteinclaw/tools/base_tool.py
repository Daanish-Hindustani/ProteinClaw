"""Base classes for tool wrappers.

Every protein-design tool is wrapped in a `BaseTool` subclass with two
responsibilities:

1. Declare its public surface — `name`, `description`, `input_schema`,
   `output_schema`, `examples` — so the Sub-Agent Branching Service can
   pick a tool by reading its description and validate its inputs.
2. Hide the actual execution behind `_execute`, which the public
   `invoke()` method wraps with input validation, latency recording, and
   typed error handling.

Errors raise `ToolExecutionError` (typed). They are NEVER swallowed —
the `Registry.invoke()` wrapper records the failure as a trace event and
re-raises. Quality bar in this repo is explicit: silent failures are
disallowed (see `CLAUDE.md`).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolStatus(StrEnum):
    """Outcome of one tool invocation."""

    SUCCESS = "success"
    FAILURE = "failure"


class ToolExample(BaseModel):
    """One worked example pairing inputs and outputs.

    Examples are surfaced to the Sub-Agent Branching Service so an LLM
    picking a tool can ground its choice in concrete prior usage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]


class ToolOutput(BaseModel):
    """Generic output envelope returned by `BaseTool.invoke`.

    Attributes:
        tool_name: The tool that produced this output.
        status: SUCCESS for a clean run; FAILURE never appears here because
            failures raise ToolExecutionError instead. Kept as a field so the
            envelope is uniform across both code paths in the Trace Store.
        payload: Serialized output_schema instance (model_dump()). Callers
            who want typed access can re-validate via the tool's output_schema.
        stderr: Captured stderr from the underlying backend (mostly real
            tools; mocks usually leave it empty).
        metrics: Free-form numeric metrics — at minimum `latency_ms`. Real
            backends add cost, gpu_seconds, etc.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    status: ToolStatus
    payload: dict[str, Any]
    stderr: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class ToolExecutionError(RuntimeError):
    """Raised by `BaseTool.invoke` for any input, runtime, or output failure.

    The Registry catches it, emits a `tool.failed` trace event, and re-raises.
    Typed so callers can distinguish tool failures from programmer bugs.

    Attributes:
        tool_name: The tool that failed.
        stderr: Optional captured stderr; useful for debugging real backends.
    """

    def __init__(self, tool_name: str, message: str, *, stderr: str = "") -> None:
        """Construct a typed error attached to `tool_name`."""
        super().__init__(f"[{tool_name}] {message}")
        self.tool_name = tool_name
        self.stderr = stderr


class ToolInvocation(BaseModel):
    """One recorded invocation, used for performance tracking on the registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invocation_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float
    status: ToolStatus
    error: str | None = None


class BaseTool(ABC):
    """Abstract base for every tool wrapper.

    Subclasses set the four ClassVars below and implement `_execute`. The
    public `invoke()` is the only entry point external callers should use —
    it validates inputs against `input_schema`, runs `_execute`, type-checks
    the result against `output_schema`, and wraps everything in a
    `ToolOutput` envelope. Failures raise `ToolExecutionError`.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    examples: ClassVar[tuple[ToolExample, ...]] = ()

    @abstractmethod
    async def _execute(self, inputs: BaseModel) -> BaseModel:
        """Run the underlying backend.

        Args:
            inputs: A validated instance of `input_schema`.

        Returns:
            An instance of `output_schema`.

        Raises:
            ToolExecutionError: When the backend fails.
        """

    async def invoke(self, raw_inputs: dict[str, Any]) -> ToolOutput:
        """Validate, execute, and wrap one tool call.

        Args:
            raw_inputs: Untrusted dict, typically straight from an LLM. Must
                conform to `input_schema`.

        Returns:
            A `ToolOutput` with `status=SUCCESS` on a clean run.

        Raises:
            ToolExecutionError: For input validation failures, backend
                errors, or output-shape mismatches. Never returns FAILURE
                in the envelope — failures are exceptions.
        """
        try:
            inputs = self.input_schema.model_validate(raw_inputs)
        except ValidationError as e:
            raise ToolExecutionError(self.name, f"input validation failed: {e}") from e

        start = time.monotonic()
        try:
            output = await self._execute(inputs)
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(self.name, f"backend error: {e}") from e
        latency_ms = (time.monotonic() - start) * 1000.0

        if not isinstance(output, self.output_schema):
            raise ToolExecutionError(
                self.name,
                f"output type {type(output).__name__} is not {self.output_schema.__name__}",
            )

        return ToolOutput(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            payload=output.model_dump(),
            metrics={"latency_ms": latency_ms},
        )

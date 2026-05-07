"""Tool Registry.

Single source of truth for tool names, descriptions, schemas, examples, and
runtime metrics (PROJECT.md §Tool Registry). Sub-agents pick tools by
reading `describe_all()` and invoke them via `invoke()`.

The registry records every invocation (success or failure) in an in-memory
list. Phase 5 promotes this to the SQLite Trace Store; the Protocol surface
on the registry stays the same.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from proteinclaw.tools.base_tool import (
    BaseTool,
    ToolExample,
    ToolExecutionError,
    ToolInvocation,
    ToolOutput,
    ToolStatus,
)


class ToolDescription(BaseModel):
    """Public description an LLM uses to pick a tool.

    Schemas are exposed as JSON-Schema dicts (Pydantic's `model_json_schema`)
    so a non-Python caller can consume them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    examples: tuple[ToolExample, ...] = ()


class DuplicateToolError(ValueError):
    """Raised when registering a tool whose name is already registered."""


class UnknownToolError(KeyError):
    """Raised when looking up or invoking a tool that is not registered."""


class ToolRegistry:
    """Registry of available tools plus an invocation log.

    Single-process, single-instance use is the intended pattern. The
    registry is constructed at session start by the orchestrator and
    threaded through to sub-agents via dependency injection.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._tools: dict[str, BaseTool] = {}
        self._invocations: list[ToolInvocation] = []

    def register(self, tool: BaseTool) -> None:
        """Register `tool` under its declared `name`.

        Args:
            tool: A `BaseTool` instance.

        Raises:
            DuplicateToolError: If a tool with the same name is already
                registered. Re-registering would silently shadow earlier
                tools and break invocation audit trails — explicit failure
                is safer.
        """
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def find_by_name(self, name: str) -> BaseTool:
        """Return the registered tool named `name`.

        Raises:
            UnknownToolError: If no tool with that name is registered.
        """
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name]

    def describe_all(self) -> list[ToolDescription]:
        """Return public descriptions for every registered tool, sorted by name."""
        return [
            ToolDescription(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema.model_json_schema(),
                output_schema=t.output_schema.model_json_schema(),
                examples=t.examples,
            )
            for t in sorted(self._tools.values(), key=lambda t: t.name)
        ]

    def invocations(self) -> tuple[ToolInvocation, ...]:
        """Return a snapshot of recorded invocations in append order."""
        return tuple(self._invocations)

    async def invoke(self, name: str, raw_inputs: dict[str, Any]) -> ToolOutput:
        """Invoke `name(raw_inputs)`, record the outcome, and re-raise on failure.

        Args:
            name: Registered tool name.
            raw_inputs: Untrusted input dict, validated by the tool.

        Returns:
            The tool's `ToolOutput` envelope.

        Raises:
            UnknownToolError: If `name` is not registered.
            ToolExecutionError: If the tool fails for any reason. The
                failure is recorded as a `ToolInvocation` with status=FAILURE
                before re-raising.
        """
        tool = self.find_by_name(name)
        try:
            output = await tool.invoke(raw_inputs)
        except ToolExecutionError as e:
            self._record(
                tool.name,
                latency_ms=output_latency(None),
                status=ToolStatus.FAILURE,
                error=str(e),
            )
            raise
        self._record(
            tool.name,
            latency_ms=float(output.metrics.get("latency_ms", 0.0)),
            status=output.status,
        )
        return output

    def _record(
        self,
        tool_name: str,
        *,
        latency_ms: float,
        status: ToolStatus,
        error: str | None = None,
    ) -> None:
        """Append one invocation record."""
        self._invocations.append(
            ToolInvocation(
                tool_name=tool_name,
                latency_ms=latency_ms,
                status=status,
                error=error,
            )
        )


def output_latency(output: ToolOutput | None) -> float:
    """Extract latency_ms from a ToolOutput, or 0.0 if unavailable.

    Used by the registry's failure path where no envelope was produced.
    Lifted to module level so it stays trivial to inline-test.
    """
    if output is None:
        return 0.0
    value = output.metrics.get("latency_ms", 0.0)
    return float(value)

"""Adapter around Nous Research ``hermes-agent``.

ProteinClaw treats Hermes as the harness only. This module owns the small
compatibility layer between Hermes ``AIAgent`` objects and ProteinClaw's stable
trace schema.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


DEFAULT_HERMES_MODEL = "anthropic/claude-sonnet-4.6"


@dataclass
class ResearchScoutDefinition:
    """Read-only Hermes scout configuration used by the ``research_scout`` tool."""

    name: str
    description: str
    model: str
    prompt: str
    tools: list[str] = field(default_factory=list)


@dataclass
class HermesAgentOptions:
    """Harness-agnostic options for one Hermes ``AIAgent`` run."""

    ephemeral_system_prompt: str
    model: str
    max_iterations: int
    cwd: str
    session_id: str
    toolsets: list[dict[str, Any]] = field(default_factory=list)
    enabled_toolsets: list[str] = field(default_factory=list)
    research_scouts: dict[str, ResearchScoutDefinition] | None = None


class HermesHarness:
    """Thin, testable wrapper for ``run_agent.AIAgent``.

    ``agent_cls`` is injectable so unit tests do not need the live Hermes
    package or provider credentials. In production we import ``AIAgent`` lazily
    from the upstream ``run_agent`` module requested by the migration plan.
    """

    def __init__(self, options: HermesAgentOptions, *, agent_cls: Any = None) -> None:
        self.options = options
        self.agent_cls = agent_cls or self._load_agent_cls()
        self.agent = self._instantiate_agent()

    @staticmethod
    def _load_agent_cls() -> Any:
        try:
            from run_agent import AIAgent  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "hermes-agent is not importable. Install it with "
                "`git+https://github.com/NousResearch/hermes-agent.git`."
            ) from exc
        return AIAgent

    def _tools_for_agent(self) -> list[Any]:
        tools: list[Any] = []
        for toolset in self.options.toolsets:
            tools.extend(toolset.get("tools", []))
        return tools

    def _instantiate_agent(self) -> Any:
        tools = self._tools_for_agent()
        kwargs = {
            "model": self.options.model,
            "ephemeral_system_prompt": self.options.ephemeral_system_prompt,
            "max_iterations": self.options.max_iterations,
            "tools": tools,
            "toolsets": self.options.toolsets,
            "enabled_toolsets": self.options.enabled_toolsets,
            "cwd": self.options.cwd,
            "session_id": self.options.session_id,
        }
        # Upstream versions differ in constructor strictness. Prefer the full
        # explicit surface, then progressively fall back while preserving the
        # prompt/model/max-iteration contract.
        attempts = [
            kwargs,
            {k: kwargs[k] for k in ("model", "ephemeral_system_prompt", "max_iterations", "tools", "cwd")},
            {k: kwargs[k] for k in ("model", "ephemeral_system_prompt", "tools")},
            {k: kwargs[k] for k in ("model", "ephemeral_system_prompt")},
        ]
        last_exc: Exception | None = None
        for attempt in attempts:
            try:
                return self.agent_cls(**attempt)
            except TypeError as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def run(self, prompt: str, on_event: Optional[Callable[[dict[str, Any]], None]] = None) -> dict[str, Any]:
        """Run the prompt and emit normalized ProteinClaw events.

        The return value always has summary-ish fields so ``core`` can populate
        ``RunSummary`` without depending on a Hermes-specific result class.
        """
        on_event = on_event or (lambda _event: None)
        result = await self._call_agent(prompt, on_event)
        return self._summary_from_result(result)

    async def _call_agent(self, prompt: str, on_event: Callable[[dict[str, Any]], None]) -> Any:
        for method_name in ("run", "query", "ask", "chat"):
            method = getattr(self.agent, method_name, None)
            if method is None:
                continue
            try:
                result = method(prompt, callback=on_event)
            except TypeError:
                try:
                    result = method(prompt, on_event=on_event)
                except TypeError:
                    result = method(prompt)
            return await self._consume_result(result, on_event)
        raise RuntimeError("Hermes AIAgent exposes none of run/query/ask/chat")

    async def _consume_result(self, result: Any, on_event: Callable[[dict[str, Any]], None]) -> Any:
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "__aiter__"):
            last: Any = None
            async for item in result:
                event = normalize_hermes_event(item)
                if event:
                    on_event(event)
                last = item
            return last
        if inspect.isgenerator(result):
            last = None
            for item in result:
                event = normalize_hermes_event(item)
                if event:
                    on_event(event)
                last = item
            return last
        event = normalize_hermes_event(result)
        if event:
            on_event(event)
        return result

    def _summary_from_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return {
                "final_text": str(result.get("final_text") or result.get("text") or result.get("output") or ""),
                "num_turns": int(result.get("num_turns") or result.get("turns") or 0),
                "total_cost_usd": result.get("total_cost_usd") or result.get("cost_usd"),
                "duration_ms": result.get("duration_ms"),
                "session_id": str(result.get("session_id") or self.options.session_id),
            }
        text = ""
        for attr in ("final_text", "text", "output", "content"):
            if hasattr(result, attr):
                text = str(getattr(result, attr) or "")
                break
        return {
            "final_text": text,
            "num_turns": int(getattr(result, "num_turns", 0) or getattr(result, "turns", 0) or 0),
            "total_cost_usd": getattr(result, "total_cost_usd", None),
            "duration_ms": getattr(result, "duration_ms", None),
            "session_id": str(getattr(result, "session_id", self.options.session_id)),
        }


def normalize_hermes_event(event: Any) -> dict[str, Any] | None:
    """Map likely Hermes callback/event shapes into ProteinClaw trace events."""
    if event is None:
        return None
    if not isinstance(event, dict):
        data = {k: getattr(event, k) for k in dir(event) if not k.startswith("_") and not callable(getattr(event, k))}
    else:
        data = dict(event)
    typ = str(data.get("type") or data.get("event") or data.get("kind") or "")
    low = typ.lower()
    if low in {"assistant_text", "text", "assistant_message", "message"}:
        return {"type": "assistant_text", "text": str(data.get("text") or data.get("content") or "")}
    if low in {"thinking", "reasoning", "assistant_thinking"}:
        return {"type": "thinking", "text": str(data.get("text") or data.get("thinking") or data.get("content") or "")}
    if low in {"tool_use", "tool_call", "tool_start"}:
        return {
            "type": "tool_use",
            "tool_use_id": str(data.get("tool_use_id") or data.get("id") or data.get("call_id") or ""),
            "name": str(data.get("name") or data.get("tool") or data.get("tool_name") or ""),
            "input": data.get("input") if "input" in data else data.get("args", {}),
        }
    if low in {"tool_result", "tool_output", "tool_end"}:
        return {
            "type": "tool_result",
            "tool_use_id": str(data.get("tool_use_id") or data.get("id") or data.get("call_id") or ""),
            "is_error": data.get("is_error") or data.get("error") is not None,
            "content": data.get("content") if "content" in data else data.get("output"),
        }
    if low in {"subagent_spawn", "delegate_task", "agent_spawn"}:
        return {
            "type": "subagent_spawn",
            "tool_use_id": str(data.get("tool_use_id") or data.get("id") or ""),
            "subagent_type": str(data.get("subagent_type") or data.get("agent") or data.get("name") or "research"),
            "description": str(data.get("description") or data.get("task") or ""),
        }
    return None


__all__ = [
    "DEFAULT_HERMES_MODEL",
    "HermesAgentOptions",
    "HermesHarness",
    "ResearchScoutDefinition",
    "normalize_hermes_event",
]

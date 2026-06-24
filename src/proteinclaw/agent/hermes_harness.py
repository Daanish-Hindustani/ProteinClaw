"""Adapter around Nous Research ``hermes-agent`` (``run_agent.AIAgent``).

ProteinClaw treats Hermes as the harness only. This module owns the small
compatibility layer between Hermes' ``AIAgent`` and ProteinClaw's stable trace
schema:

* it registers ProteinClaw tool specs into Hermes' tool registry
  (``model_tools.registry``) under our toolset names,
* it constructs an ``AIAgent`` scoped to those toolset names (plus any native
  Hermes toolsets we opt into, e.g. ``web``/``skills``),
* it drives one autonomous run via ``AIAgent.run_conversation`` and maps Hermes'
  tool/text/reasoning callbacks onto ``proteinclaw`` trace events, and
* it normalises the result dict into harness-agnostic summary fields.

The driving contract here is verified against the installed ``run_agent`` API:
``run_conversation(user_message, ...) -> dict`` is the full multi-tool loop;
tool calls surface via ``tool_start_callback``/``tool_complete_callback``,
assistant text via ``interim_assistant_callback``, and model reasoning via
``reasoning_callback`` (``event_callback`` is a session-lifecycle channel only).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from proteinclaw.agent.mcp_tools import HermesToolSpec, register_specs


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
    session_id: str
    cwd: str = ""
    # Hermes toolset NAMES this agent may call (ours + any native ones).
    enabled_toolsets: list[str] = field(default_factory=list)
    # ProteinClaw tool specs to register into the Hermes registry before the run.
    specs: list[HermesToolSpec] = field(default_factory=list)
    research_scouts: dict[str, ResearchScoutDefinition] | None = None


def _load_agent_cls() -> Any:
    try:
        from run_agent import AIAgent  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "hermes-agent is not importable. Install it with "
            "`pip install 'hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git'`."
        ) from exc
    return AIAgent


def _load_registry() -> Any:
    try:
        from model_tools import registry  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "hermes-agent's model_tools registry is not importable; cannot "
            "register ProteinClaw tools."
        ) from exc
    return registry


def _looks_like_error(result_text: str) -> bool:
    """Best-effort: does a tool-result string carry our error envelope?"""
    return '"error"' in result_text and (
        '"summary": "Error' in result_text or '"summary":"Error' in result_text
    )


class HermesHarness:
    """Testable wrapper for ``run_agent.AIAgent``.

    ``agent_cls`` and ``hermes_registry`` are injectable so unit tests run
    without the live Hermes package or provider credentials. In production both
    are loaded lazily from the installed ``run_agent`` / ``model_tools``.
    """

    def __init__(
        self,
        options: HermesAgentOptions,
        *,
        agent_cls: Any = None,
        hermes_registry: Any = None,
        register: bool = True,
    ) -> None:
        self.options = options
        self.agent_cls = agent_cls or _load_agent_cls()
        self.registry = hermes_registry if hermes_registry is not None else _load_registry()
        if register and options.specs:
            register_specs(self.registry, options.specs)

    def _build_callbacks(
        self, on_event: Callable[[dict[str, Any]], None]
    ) -> dict[str, Callable[..., None]]:
        """Wire Hermes' per-event callbacks onto ProteinClaw trace events."""

        def _tool_start(tool_call_id: str, name: str, args: Any) -> None:
            on_event({
                "type": "tool_use",
                "tool_use_id": str(tool_call_id or ""),
                "name": str(name or ""),
                "input": args if isinstance(args, dict) else {"value": args},
            })

        def _tool_complete(tool_call_id: str, name: str, args: Any, function_result: Any) -> None:
            text = function_result if isinstance(function_result, str) else str(function_result)
            on_event({
                "type": "tool_result",
                "tool_use_id": str(tool_call_id or ""),
                "is_error": _looks_like_error(text),
                "content": function_result,
            })

        def _interim(visible_text: str, already_streamed: bool = False) -> None:
            if visible_text:
                on_event({"type": "assistant_text", "text": str(visible_text)})

        def _reasoning(reasoning_text: str) -> None:
            if reasoning_text:
                on_event({"type": "thinking", "text": str(reasoning_text)})

        return {
            "tool_start_callback": _tool_start,
            "tool_complete_callback": _tool_complete,
            "interim_assistant_callback": _interim,
            "reasoning_callback": _reasoning,
        }

    def _instantiate_agent(self, on_event: Optional[Callable[[dict[str, Any]], None]]) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.options.model,
            "ephemeral_system_prompt": self.options.ephemeral_system_prompt,
            "max_iterations": self.options.max_iterations,
            "session_id": self.options.session_id or None,
            "enabled_toolsets": self.options.enabled_toolsets or None,
            "quiet_mode": True,
            "skip_context_files": True,
            "skip_memory": True,
        }
        if on_event is not None:
            kwargs.update(self._build_callbacks(on_event))
        return self.agent_cls(**kwargs)

    async def run(
        self,
        prompt: str,
        on_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        """Run one autonomous campaign and return normalized summary fields."""
        agent = self._instantiate_agent(on_event)
        # ``run_conversation`` is synchronous and long-running; offload it so the
        # asyncio event loop (and Ctrl-C handling in ``core._drive``) stays live.
        result = await asyncio.to_thread(agent.run_conversation, prompt)
        try:
            close = getattr(agent, "close", None)
            if callable(close):
                close()
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            pass
        return self._summary_from_result(result)

    def _summary_from_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return {
                "final_text": str(
                    result.get("final_response")
                    or result.get("final_text")
                    or result.get("text")
                    or ""
                ),
                "num_turns": int(result.get("api_calls") or result.get("num_turns") or 0),
                "total_cost_usd": result.get("estimated_cost_usd") or result.get("total_cost_usd"),
                "duration_ms": result.get("duration_ms"),
                "session_id": str(result.get("session_id") or self.options.session_id),
                "completed": bool(result.get("completed", True)),
            }
        text = ""
        for attr in ("final_response", "final_text", "text", "output", "content"):
            if hasattr(result, attr):
                text = str(getattr(result, attr) or "")
                break
        return {
            "final_text": text,
            "num_turns": int(getattr(result, "api_calls", 0) or 0),
            "total_cost_usd": getattr(result, "estimated_cost_usd", None),
            "duration_ms": getattr(result, "duration_ms", None),
            "session_id": str(getattr(result, "session_id", self.options.session_id)),
            "completed": True,
        }


__all__ = [
    "DEFAULT_HERMES_MODEL",
    "HermesAgentOptions",
    "HermesHarness",
    "ResearchScoutDefinition",
]

"""LLMClient Protocol and a stub implementation for tests.

The orchestrator and sub-agents rely on an LLM for planning and
skill-driven reasoning. We keep the interface narrow and provider-agnostic
so we can flip between Claude (default), OpenAI, Gemini, and others via
the `litellm` adapter without touching callers.

Phase 4 ships:

- `LLMClient` Protocol: `complete()` for plain text and
  `complete_structured()` for typed output (Pydantic).
- `StubLLMClient`: returns canned responses; used in tests.
- `frozen_system_prompt()`: builds the immutable system block at session
  start so Anthropic prompt caching stays warm.

A real `LiteLLMClient` lands later — its absence does not block the Phase 4
end-to-end mocked run because the planner has a heuristic fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict


class Message(BaseModel):
    """One chat message exchanged with the LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str  # "user" | "assistant" | "system"
    content: str


T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic LLM surface used by orchestrator and sub-agents."""

    async def complete(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
    ) -> str:
        """Return free-form text for the given conversation."""
        ...

    async def complete_structured(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
        response_model: type[T],
    ) -> T:
        """Return a validated instance of `response_model`."""
        ...


class StubLLMClient:
    """Deterministic stub used in tests.

    Each call pops the next response from a queue. `complete` consumes
    `text_responses`; `complete_structured` consumes `structured_responses`.
    Empty queue raises so tests fail loudly if expectations diverge from
    implementation.
    """

    def __init__(
        self,
        *,
        text_responses: Sequence[str] = (),
        structured_responses: Sequence[BaseModel] = (),
    ) -> None:
        """Bind canned response queues."""
        self._text: list[str] = list(text_responses)
        self._structured: list[BaseModel] = list(structured_responses)

    async def complete(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
    ) -> str:
        """Return the next canned text response."""
        del system, messages
        if not self._text:
            raise AssertionError("StubLLMClient.complete called with no canned responses left")
        return self._text.pop(0)

    async def complete_structured(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
        response_model: type[T],
    ) -> T:
        """Return the next canned structured response, type-checked."""
        del system, messages
        if not self._structured:
            raise AssertionError(
                "StubLLMClient.complete_structured called with no canned responses left"
            )
        candidate = self._structured.pop(0)
        if not isinstance(candidate, response_model):
            raise AssertionError(
                f"StubLLMClient response type {type(candidate).__name__} "
                f"is not {response_model.__name__}"
            )
        return candidate


def frozen_system_prompt(*sections: str) -> str:
    """Build a single immutable system prompt from labeled sections.

    The orchestrator calls this once at session start with knowledge-store
    metadata, the active skill list, and tool descriptions. The result is
    cached server-side (Anthropic prompt caching) for the rest of the
    session. Live changes go to per-turn user messages, never here.
    """
    return "\n\n".join(s.strip() for s in sections if s.strip())

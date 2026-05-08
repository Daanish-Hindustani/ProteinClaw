"""Concrete `LLMClient` backed by LiteLLM (Claude path).

Phase 6.5 ships a Claude-only client. Provider-agnostic plumbing is
deliberately deferred until we actually need a second provider; LiteLLM
underneath makes that future swap a one-line change to ``model``.

Structured outputs are produced by asking Claude for a JSON object
matching the response model's schema, then validating with Pydantic.
The model name is configurable so the Planner / Evaluator can tier
calls (cheap model for routine plans, stronger for reflection).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from proteinclaw.common.llm import Message

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_SECONDS = 60.0


class LLMResponseError(RuntimeError):
    """Raised when the LLM response can't be parsed into the requested model."""


class LiteLLMClient:
    """LLMClient implementation calling Anthropic via LiteLLM.

    LiteLLM is already a dependency. Imports happen lazily inside methods
    so test environments that mock the client never pay the import cost.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Bind credentials + default model."""
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    async def complete(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
    ) -> str:
        """Return free-form text from Claude for the conversation."""
        resp = await self._call(system, messages)
        return _extract_text(resp)

    async def complete_structured(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
        response_model: type[T],
    ) -> T:
        """Return a validated instance of `response_model`.

        We append a system instruction with the JSON schema and ask the
        model to emit a single JSON object. The first JSON object found
        in the response is parsed; mismatches raise `LLMResponseError`.
        """
        schema = response_model.model_json_schema()
        schema_msg = (
            "Respond with a single JSON object matching this schema. "
            "Do not wrap in markdown fences. Do not add prose before or after.\n"
            f"Schema:\n{json.dumps(schema)}"
        )
        full_system = (system or "").strip()
        full_system = f"{full_system}\n\n{schema_msg}".strip()
        resp = await self._call(full_system, messages)
        text = _extract_text(resp)
        payload = _extract_json_object(text)
        try:
            return response_model.model_validate(payload)
        except ValidationError as e:
            raise LLMResponseError(
                f"LLM response did not match {response_model.__name__}: {e}"
            ) from e

    async def _call(self, system: str | None, messages: Sequence[Message]) -> Any:
        """Invoke LiteLLM's async completion. Returns the raw response object."""
        import litellm  # imported lazily so tests can stub the symbol

        body: list[dict[str, str]] = []
        if system:
            body.append({"role": "system", "content": system})
        for m in messages:
            body.append({"role": m.role, "content": m.content})
        return await litellm.acompletion(
            model=f"anthropic/{self._model}",
            api_key=self._api_key,
            messages=body,
            timeout=self._timeout,
        )


def _extract_text(response: Any) -> str:
    """Pull the assistant's text content out of a LiteLLM response object."""
    try:
        return cast("str", response.choices[0].message.content)
    except (AttributeError, IndexError) as e:  # pragma: no cover - defensive
        raise LLMResponseError(f"unexpected LiteLLM response shape: {response!r}") from e


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort: find the first balanced JSON object in `text` and parse it.

    Tolerant of leading/trailing prose even though we asked the model
    not to add any. If parsing fails, raises `LLMResponseError`.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        raise LLMResponseError(f"no JSON object found in LLM response: {text[:200]}")
    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LLMResponseError(f"failed to parse JSON: {e}") from e
    if not isinstance(loaded, dict):
        raise LLMResponseError(f"top-level JSON value was {type(loaded).__name__}, expected object")
    return loaded

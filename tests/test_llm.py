"""Tests for common/llm.py — Protocol conformance, StubLLMClient, frozen prompt."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from proteinclaw.common.llm import (
    LLMClient,
    Message,
    StubLLMClient,
    frozen_system_prompt,
)


class _Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    steps: tuple[str, ...]


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubLLMClient(), LLMClient)


async def test_stub_complete_returns_canned_text() -> None:
    stub = StubLLMClient(text_responses=("hello",))
    out = await stub.complete(system=None, messages=())
    assert out == "hello"


async def test_stub_complete_exhausts() -> None:
    stub = StubLLMClient()
    with pytest.raises(AssertionError):
        await stub.complete(system=None, messages=())


async def test_stub_complete_structured_returns_typed() -> None:
    stub = StubLLMClient(structured_responses=(_Plan(steps=("a", "b")),))
    out = await stub.complete_structured(system=None, messages=(), response_model=_Plan)
    assert out.steps == ("a", "b")


async def test_stub_complete_structured_type_mismatch_raises() -> None:
    class _Other(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        x: int

    stub = StubLLMClient(structured_responses=(_Plan(steps=("a",)),))
    with pytest.raises(AssertionError):
        await stub.complete_structured(system=None, messages=(), response_model=_Other)


def test_message_is_frozen() -> None:
    m = Message(role="user", content="hi")
    with pytest.raises(Exception):  # noqa: B017
        m.content = "mut"  # type: ignore[misc]


def test_frozen_system_prompt_strips_and_joins() -> None:
    out = frozen_system_prompt("  one  ", "", "two", "  ")
    assert out == "one\n\ntwo"

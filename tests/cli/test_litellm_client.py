"""Tests for common/litellm_client.py — JSON extraction + validation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from proteinclaw.common import litellm_client
from proteinclaw.common.litellm_client import (
    LiteLLMClient,
    LLMResponseError,
    _extract_json_object,
)


class _Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str
    target: str | None = None


def test_constructor_requires_api_key() -> None:
    with pytest.raises(ValueError):
        LiteLLMClient(api_key="")


def test_extract_json_clean() -> None:
    body = '{"task_type": "binder_design", "target": "1ABC"}'
    out = _extract_json_object(body)
    assert out == {"task_type": "binder_design", "target": "1ABC"}


def test_extract_json_with_prose_around() -> None:
    body = 'Here is the plan:\n{"task_type": "binder_design"}\nDone.'
    out = _extract_json_object(body)
    assert out["task_type"] == "binder_design"


def test_extract_json_with_code_fence() -> None:
    body = '```json\n{"task_type": "enzyme_design"}\n```'
    out = _extract_json_object(body)
    assert out["task_type"] == "enzyme_design"


def test_extract_json_no_object_raises() -> None:
    with pytest.raises(LLMResponseError):
        _extract_json_object("nothing useful here")


def test_extract_json_top_level_array_raises() -> None:
    with pytest.raises(LLMResponseError):
        _extract_json_object("[1, 2, 3]")


def test_extract_json_invalid_raises() -> None:
    with pytest.raises(LLMResponseError):
        _extract_json_object('{"unterminated":')


async def test_complete_structured_validates_into_response_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub litellm.acompletion so we test the parsing without network."""

    class _FakeMsg:
        content = '{"task_type": "binder_design", "target": "2XYZ"}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        def __init__(self) -> None:
            self.choices = [_FakeChoice()]

    class _FakeLitellm:
        async def acompletion(self, **_kwargs: object) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setitem(__import__("sys").modules, "litellm", _FakeLitellm())
    client = LiteLLMClient(api_key="sk-test", model="claude-sonnet-4-6")
    plan = await client.complete_structured(
        system="be helpful",
        messages=[],
        response_model=_Plan,
    )
    assert plan.task_type == "binder_design"
    assert plan.target == "2XYZ"


async def test_complete_structured_routes_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class _FakeMsg:
        content = '{"task_type": "binder_design", "target": "1UBQ"}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        def __init__(self) -> None:
            self.choices = [_FakeChoice()]

    class _FakeLitellm:
        async def acompletion(self, **kwargs: object) -> _FakeResp:
            seen.update(kwargs)
            return _FakeResp()

    monkeypatch.setitem(__import__("sys").modules, "litellm", _FakeLitellm())
    client = LiteLLMClient(
        api_key="gemini-test",
        model="gemini-2.5-flash",
        provider="gemini",
    )
    plan = await client.complete_structured(
        system="be helpful",
        messages=[],
        response_model=_Plan,
    )
    assert plan.target == "1UBQ"
    assert seen["model"] == "gemini/gemini-2.5-flash"
    assert seen["api_key"] == "gemini-test"


async def test_complete_structured_routes_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class _FakeMsg:
        content = '{"task_type": "binder_design", "target": "1UBQ"}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        def __init__(self) -> None:
            self.choices = [_FakeChoice()]

    class _FakeLitellm:
        async def acompletion(self, **kwargs: object) -> _FakeResp:
            seen.update(kwargs)
            return _FakeResp()

    monkeypatch.setitem(__import__("sys").modules, "litellm", _FakeLitellm())
    client = LiteLLMClient(
        api_key="openrouter-test",
        model="google/gemini-2.5-flash",
        provider="openrouter",
    )
    plan = await client.complete_structured(
        system="be helpful",
        messages=[],
        response_model=_Plan,
    )
    assert plan.target == "1UBQ"
    assert seen["model"] == "openrouter/google/gemini-2.5-flash"
    assert seen["api_key"] == "openrouter-test"


async def test_complete_structured_raises_on_schema_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeMsg:
        content = '{"unknown_field": 1}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        def __init__(self) -> None:
            self.choices = [_FakeChoice()]

    class _FakeLitellm:
        async def acompletion(self, **_kwargs: object) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setitem(__import__("sys").modules, "litellm", _FakeLitellm())
    client = LiteLLMClient(api_key="sk-test")
    with pytest.raises(LLMResponseError):
        await client.complete_structured(
            system=None,
            messages=[],
            response_model=_Plan,
        )


# Keep the linter from flagging the imported module as unused.
_ = litellm_client.DEFAULT_MODEL

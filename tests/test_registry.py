"""Task 1.2 — Tool dataclass + ToolRegistry + @register."""

from __future__ import annotations

import pytest

from proteinclaw.tools import Tool, ToolRegistry, registry as default_registry


@pytest.fixture
def reg() -> ToolRegistry:
    """Fresh registry per test — no leakage from the singleton."""
    return ToolRegistry()


def _ok_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }


# --- Tool dataclass ---------------------------------------------------------


def test_tool_name_must_be_namespaced() -> None:
    with pytest.raises(ValueError, match="<category>.<tool>"):
        Tool(
            name="foo",
            display_name="x",
            description="x",
            category="foo",
            parameters=_ok_schema(),
            function=lambda **_: {},
        )


def test_tool_name_category_must_agree() -> None:
    with pytest.raises(ValueError, match="disagrees with category"):
        Tool(
            name="design.x",
            display_name="x",
            description="x",
            category="data",  # mismatch
            parameters=_ok_schema(),
            function=lambda **_: {},
        )


def test_tool_rejects_bad_json_schema() -> None:
    with pytest.raises(ValueError, match="invalid JSON Schema"):
        Tool(
            name="design.x",
            display_name="x",
            description="x",
            category="design",
            parameters={"type": "not-a-real-type"},  # invalid
            function=lambda **_: {},
        )


def test_tool_gpu_requires_vram_and_image() -> None:
    with pytest.raises(ValueError, match="min_vram_gb"):
        Tool(
            name="design.x",
            display_name="x",
            description="x",
            category="design",
            parameters=_ok_schema(),
            function=lambda **_: {},
            requires_gpu=True,
            min_vram_gb=0,
            docker_image="x:1",
        )

    with pytest.raises(ValueError, match="docker_image"):
        Tool(
            name="design.x",
            display_name="x",
            description="x",
            category="design",
            parameters=_ok_schema(),
            function=lambda **_: {},
            requires_gpu=True,
            min_vram_gb=24,
            docker_image=None,
        )


def test_tool_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        Tool(
            name="design.x",
            display_name="x",
            description="x",
            category="design",
            parameters=_ok_schema(),
            function=lambda **_: {},
            timeout_s=0,
        )


# --- ToolRegistry ------------------------------------------------------------


def test_register_and_get(reg: ToolRegistry) -> None:
    @reg.register(
        name="test.fake",
        display_name="fake",
        description="d",
        category="test",
        parameters=_ok_schema(),
    )
    def fake(**kwargs):
        return {"summary": "ok", "metrics": {}, **kwargs}

    tool = reg.get_tool("test.fake")
    assert tool.name == "test.fake"
    assert tool.function(x=1)["x"] == 1


def test_register_duplicate_raises(reg: ToolRegistry) -> None:
    @reg.register(
        name="test.fake",
        display_name="fake",
        description="d",
        category="test",
        parameters=_ok_schema(),
    )
    def fake1(**_):
        return {"summary": "ok", "metrics": {}}

    with pytest.raises(ValueError, match="duplicate tool name"):

        @reg.register(
            name="test.fake",
            display_name="fake2",
            description="d",
            category="test",
            parameters=_ok_schema(),
        )
        def fake2(**_):
            return {"summary": "ok", "metrics": {}}


def test_register_invalid_schema_raises(reg: ToolRegistry) -> None:
    with pytest.raises(ValueError, match="invalid JSON Schema"):

        @reg.register(
            name="test.bad",
            display_name="bad",
            description="d",
            category="test",
            parameters={"type": "not-real"},
        )
        def bad(**_):
            return {"summary": "ok", "metrics": {}}


def test_get_tool_missing_raises(reg: ToolRegistry) -> None:
    with pytest.raises(KeyError, match="not registered"):
        reg.get_tool("nope.nope")


def test_list_tools_by_category(reg: ToolRegistry) -> None:
    @reg.register(
        name="test.a",
        display_name="a",
        description="d",
        category="test",
        parameters=_ok_schema(),
    )
    def a(**_):
        return {"summary": "ok", "metrics": {}}

    @reg.register(
        name="other.b",
        display_name="b",
        description="d",
        category="other",
        parameters=_ok_schema(),
    )
    def b(**_):
        return {"summary": "ok", "metrics": {}}

    names = [t.name for t in reg.list_tools(category="test")]
    assert names == ["test.a"]
    assert "test" in reg.categories() and "other" in reg.categories()


def test_describe_for_planner_contains_required_fields(reg: ToolRegistry) -> None:
    @reg.register(
        name="test.fake",
        display_name="The Fake",
        description="Does a fake thing.",
        category="test",
        parameters=_ok_schema(),
    )
    def fake(**_):
        return {"summary": "ok", "metrics": {}}

    rendered = reg.describe_for_planner()
    assert "test.fake" in rendered
    assert "The Fake" in rendered
    assert "Does a fake thing." in rendered
    # JSON Schema present.
    assert '"type": "object"' in rendered or '"type":"object"' in rendered.replace(
        " ", ""
    )


def test_describe_for_planner_empty(reg: ToolRegistry) -> None:
    assert "no tools" in reg.describe_for_planner().lower()


# --- default singleton has the smoke tool auto-discovered -------------------


def test_default_singleton_has_smoke_tool() -> None:
    """Auto-discovery wires up tools/_smoke/tool.yaml on package import."""
    assert "debug._smoke" in default_registry
    tool = default_registry.get_tool("debug._smoke")
    assert tool.requires_gpu is True
    assert tool.docker_image

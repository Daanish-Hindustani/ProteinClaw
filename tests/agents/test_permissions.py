"""Tests for ToolPermissionSet — parent/child factories, require()."""

from __future__ import annotations

import pytest

from proteinclaw.agents.permissions import (
    PermissionDeniedError,
    ToolPermissionSet,
)


def test_parent_has_full_capabilities() -> None:
    p = ToolPermissionSet.parent()
    assert p.can_delegate
    assert p.can_write_memory
    assert p.can_ask_user
    assert p.can_run_sandbox
    assert p.can_invoke_tools


def test_child_is_locked_down_per_hermes() -> None:
    p = ToolPermissionSet.child()
    assert not p.can_delegate
    assert not p.can_write_memory
    assert not p.can_ask_user
    # Children retain sandbox and tool access (we want analysis).
    assert p.can_run_sandbox
    assert p.can_invoke_tools


def test_require_raises_with_permission_name() -> None:
    p = ToolPermissionSet.child()
    with pytest.raises(PermissionDeniedError) as ex:
        p.require("can_delegate")
    assert ex.value.permission == "can_delegate"


def test_require_passes_when_granted() -> None:
    ToolPermissionSet.parent().require("can_delegate")  # no exception


def test_require_unknown_permission_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        ToolPermissionSet.parent().require("can_take_over_the_world")


def test_dataclass_is_frozen() -> None:
    p = ToolPermissionSet.parent()
    with pytest.raises(Exception):  # noqa: B017 — dataclasses.FrozenInstanceError or AttributeError
        p.can_delegate = False  # type: ignore[misc]

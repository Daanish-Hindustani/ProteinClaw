"""Tests for agents/branch_result.py — immutability, with_status transitions, round-trip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proteinclaw.agents.branch_result import BranchResult, BranchStatus


def _running() -> BranchResult:
    return BranchResult(
        session_id="s1",
        task_id="t1",
        skill_version_id="binder_design@v3",
    )


def test_branch_result_defaults() -> None:
    b = _running()
    assert b.branch_id  # auto-generated
    assert b.status == BranchStatus.RUNNING
    assert b.depth == 0
    assert b.parent_branch_id is None
    assert b.finished_at is None


def test_branch_result_is_frozen() -> None:
    b = _running()
    with pytest.raises(ValidationError):
        b.status = BranchStatus.COMPLETED  # type: ignore[misc]


def test_with_status_completed_sets_payload_and_finished_at() -> None:
    b = _running()
    done = b.with_status(BranchStatus.COMPLETED, payload={"design": "ABC"})
    assert b.status == BranchStatus.RUNNING  # original untouched
    assert done.status == BranchStatus.COMPLETED
    assert done.payload == {"design": "ABC"}
    assert done.finished_at is not None
    assert done.error is None


def test_with_status_failed_sets_error() -> None:
    b = _running()
    failed = b.with_status(BranchStatus.FAILED, error="tool exploded")
    assert failed.status == BranchStatus.FAILED
    assert failed.error == "tool exploded"
    assert failed.finished_at is not None


def test_with_status_no_payload_preserves_existing() -> None:
    b = _running().with_status(BranchStatus.COMPLETED, payload={"a": 1})
    again = b.with_status(BranchStatus.BACKTRACKED)
    assert again.payload == {"a": 1}


def test_branch_result_round_trip() -> None:
    b = _running().with_status(BranchStatus.COMPLETED, payload={"x": 1})
    assert BranchResult.model_validate_json(b.model_dump_json()) == b


def test_branch_result_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        BranchResult(  # type: ignore[call-arg]
            session_id="s1",
            task_id="t1",
            unknown="field",
        )

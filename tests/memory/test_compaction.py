"""Tests for memory/compaction.py — preserved kinds, structured template, edge cases."""

from __future__ import annotations

import pytest

from proteinclaw.common.logging import EventKind, TraceEvent
from proteinclaw.memory.compaction import (
    PRESERVED_KINDS,
    Compactor,
    EmptyCompactionRangeError,
)


def _e(
    kind: EventKind,
    *,
    session_id: str = "s1",
    payload: dict[str, object] | None = None,
    branch_id: str | None = None,
) -> TraceEvent:
    return TraceEvent(
        session_id=session_id,
        component="x",
        kind=kind,
        branch_id=branch_id,
        payload=payload or {},
    )


def test_should_compact_threshold() -> None:
    c = Compactor(threshold=3)
    assert not c.should_compact([_e(EventKind.SESSION_STARTED)])
    assert c.should_compact([_e(EventKind.SESSION_STARTED)] * 3)


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Compactor(threshold=0)


def test_compact_empty_raises() -> None:
    with pytest.raises(EmptyCompactionRangeError):
        Compactor().compact([])


def test_compact_multi_session_raises() -> None:
    with pytest.raises(ValueError):
        Compactor().compact(
            [
                _e(EventKind.SESSION_STARTED, session_id="a"),
                _e(EventKind.SESSION_STARTED, session_id="b"),
            ]
        )


def test_compact_preserves_critical_event_kinds() -> None:
    events = [
        _e(EventKind.SESSION_STARTED, payload={"user_request": "design a binder"}),
        _e(EventKind.PLAN_PRODUCED, payload={"task_count": 1}),
        _e(EventKind.BRANCH_SPAWNED, branch_id="b1"),
        _e(EventKind.TOOL_INVOKED),  # NOT preserved
        _e(EventKind.TOOL_FAILED, payload={"error": "boom"}),  # PRESERVED
        _e(EventKind.BRANCH_BACKTRACKED, branch_id="b1", payload={"reason": "tool_failed"}),
        _e(
            EventKind.EVALUATION_PRODUCED,
            branch_id="b1",
            payload={"verdict": "stop_failure"},
        ),
        _e(EventKind.SESSION_ENDED),
    ]
    result = Compactor().compact(events)
    preserved_kinds = {e.kind for e in result.preserved_events}
    # Every preserved kind in the input shows up in the output.
    expected = {
        EventKind.SESSION_STARTED,
        EventKind.PLAN_PRODUCED,
        EventKind.TOOL_FAILED,
        EventKind.BRANCH_BACKTRACKED,
        EventKind.EVALUATION_PRODUCED,
        EventKind.SESSION_ENDED,
    }
    assert expected <= preserved_kinds
    # TOOL_INVOKED is NOT preserved (it's not in PRESERVED_KINDS).
    assert EventKind.TOOL_INVOKED not in preserved_kinds


def test_preserved_kinds_are_a_strict_subset_of_event_kind() -> None:
    """Sanity guard: every preserved kind is a valid EventKind enum member."""
    for k in PRESERVED_KINDS:
        assert isinstance(k, EventKind)


def test_template_extracts_goal_from_session_started() -> None:
    events = [
        _e(EventKind.SESSION_STARTED, payload={"user_request": "binder for 1ABC"}),
        _e(EventKind.SESSION_ENDED),
    ]
    result = Compactor().compact(events)
    assert result.summary.goal == "binder for 1ABC"


def test_template_progress_counts_event_kinds() -> None:
    events = [
        _e(EventKind.PLAN_PRODUCED),
        _e(EventKind.BRANCH_SPAWNED),
        _e(EventKind.BRANCH_SPAWNED),
        _e(EventKind.BRANCH_COMPLETED),
        _e(EventKind.BRANCH_BACKTRACKED),
        _e(EventKind.EVALUATION_PRODUCED),
        _e(EventKind.TOOL_FAILED),
    ]
    result = Compactor().compact(events)
    progress = result.summary.progress
    assert "1 plan" in progress
    assert "2 branches" in progress
    assert "1 completed" in progress
    assert "1 backtracked" in progress
    assert "1 evaluations" in progress
    assert "1 tool failures" in progress


def test_template_decisions_lists_verdicts_in_order() -> None:
    events = [
        _e(
            EventKind.EVALUATION_PRODUCED,
            branch_id="b1",
            payload={"verdict": "retry"},
        ),
        _e(
            EventKind.EVALUATION_PRODUCED,
            branch_id="b2",
            payload={"verdict": "stop_success"},
        ),
    ]
    result = Compactor().compact(events)
    assert result.summary.decisions == ("b1: retry", "b2: stop_success")


def test_template_files_pulls_pdb_paths_dedup() -> None:
    events = [
        _e(EventKind.BRANCH_COMPLETED, payload={"pdb_path": "/x/a.pdb"}),
        _e(EventKind.BRANCH_COMPLETED, payload={"nested": {"pdb_path": "/x/b.pdb"}}),
        _e(EventKind.BRANCH_COMPLETED, payload={"pdb_path": "/x/a.pdb"}),  # dup
    ]
    result = Compactor().compact(events)
    assert set(result.summary.files) == {"/x/a.pdb", "/x/b.pdb"}


def test_template_next_steps_when_run_unfinished() -> None:
    events = [
        _e(EventKind.PLAN_PRODUCED),
        _e(EventKind.ITERATION_FINISHED, payload={"verdict": "retry"}),
    ]
    result = Compactor().compact(events)
    assert "continue iteration: retry" in result.summary.next_steps


def test_template_no_next_steps_when_session_ended() -> None:
    events = [
        _e(EventKind.PLAN_PRODUCED),
        _e(EventKind.ITERATION_FINISHED, payload={"verdict": "stop_success"}),
        _e(EventKind.SESSION_ENDED),
    ]
    result = Compactor().compact(events)
    assert result.summary.next_steps == ()


def test_compaction_result_records_range() -> None:
    events = [
        _e(EventKind.SESSION_STARTED),
        _e(EventKind.PLAN_PRODUCED),
        _e(EventKind.SESSION_ENDED),
    ]
    result = Compactor().compact(events)
    assert result.range_start_event_id == events[0].event_id
    assert result.range_end_event_id == events[-1].event_id
    assert result.compacted_event_count == len(events)

"""Smoke tests for TraceEvent invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proteinclaw.common.logging import EventKind, TraceEvent, configure_logging, get_logger


def test_trace_event_is_frozen() -> None:
    event = TraceEvent(
        session_id="s1",
        component="orchestrator",
        kind=EventKind.SESSION_STARTED,
    )
    with pytest.raises(ValidationError):
        event.payload = {"mutated": True}  # type: ignore[misc]


def test_trace_event_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(
            session_id="s1",
            component="orchestrator",
            kind=EventKind.SESSION_STARTED,
            unknown_field="boom",  # type: ignore[call-arg]
        )


def test_trace_event_auto_id_and_timestamp() -> None:
    a = TraceEvent(session_id="s1", component="x", kind=EventKind.SESSION_STARTED)
    b = TraceEvent(session_id="s1", component="x", kind=EventKind.SESSION_STARTED)
    assert a.event_id != b.event_id
    assert a.timestamp.tzinfo is not None  # always UTC-aware


def test_logging_configures_idempotently() -> None:
    configure_logging(level="INFO", json=True)
    configure_logging(level="DEBUG", json=False)
    log = get_logger("proteinclaw.test")
    log.info("smoke", marker=True)

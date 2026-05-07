"""Structured logging and the canonical TraceEvent record.

Every component in ProteinClaw emits TraceEvents through the trace bus. This
module defines the event shape and configures the process-wide structlog
logger. Concrete persistence (SQLite + FTS5) is added in Phase 5; the bus is
defined here so Phase 1+ code can depend on a stable interface.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field


class EventKind(StrEnum):
    """Canonical TraceEvent kinds. Add new values here, never inline strings."""

    # Lifecycle
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    # Orchestrator
    REQUEST_RECEIVED = "orchestrator.request_received"
    PLAN_PRODUCED = "orchestrator.plan_produced"
    ITERATION_STARTED = "orchestrator.iteration_started"
    ITERATION_FINISHED = "orchestrator.iteration_finished"

    # Branching / sub-agents
    BRANCH_SPAWNED = "agent.branch_spawned"
    BRANCH_COMPLETED = "agent.branch_completed"
    BRANCH_BACKTRACKED = "agent.branch_backtracked"

    # Tools
    TOOL_INVOKED = "tool.invoked"
    TOOL_SUCCEEDED = "tool.succeeded"
    TOOL_FAILED = "tool.failed"

    # Skills
    SKILL_SELECTED = "skill.selected"
    SKILL_PATCHED = "skill.patched"
    SKILL_REJECTED = "skill.rejected"

    # Evaluator
    EVALUATION_PRODUCED = "evaluator.produced"

    # Evolution
    OPTIMIZER_STEP = "evolution.optimizer_step"
    OPTIMIZER_ACCEPTED = "evolution.candidate_accepted"


class TraceEvent(BaseModel):
    """One immutable event in the run trace.

    Every component writes through this shape. Replaying events from the
    Trace Store in order must be sufficient to reconstruct the session
    (this is a correctness requirement, not a nice-to-have).

    Attributes:
        event_id: Unique id; UUIDv4.
        timestamp: UTC time the event was emitted.
        session_id: The session this event belongs to.
        component: Originating component (e.g. "orchestrator", "tool.rfdiffusion3").
        kind: Canonical EventKind (see enum).
        branch_id: Branch this event belongs to, if any.
        parent_branch_id: Parent branch (for backtracking and tree reconstruction).
        payload: Free-form JSON-serializable structured data for the event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    component: str
    kind: EventKind
    branch_id: str | None = None
    parent_branch_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def configure_logging(*, level: str = "INFO", json: bool = True) -> None:
    """Configure structlog + stdlib logging for the process.

    Idempotent. Call once at process start (CLI entrypoint, test fixture).

    Args:
        level: Standard logging level name ("DEBUG", "INFO", ...).
        json: Render JSON when True (production / structured ingestion);
            human-readable console output when False (local dev).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger named for the calling module.

    Args:
        name: Logger name; conventionally __name__ of the calling module.

    Returns:
        Bound structlog logger that respects the configured renderer.
    """
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))

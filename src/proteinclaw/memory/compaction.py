"""Trace compaction with the Hermes-validated structured template.

Long sessions accumulate large traces. Compaction collapses a slice of
events into a structured summary while preserving the events that carry
correctness signal (failures, evaluator verdicts, evolutionary edits) so
replay still answers "did this run actually succeed?" honestly.

The template is fixed: ``Goal | Progress | Decisions | Files | Next Steps``
(PLAN.md §4.5). Phase 5 ships a deterministic, template-driven compactor;
Phase 7 may swap in an LLM-driven one — same `compact()` signature, same
`CompactionResult` shape, so the swap is local.

Pure function: `compact()` takes a slice and returns a `CompactionResult`.
No I/O. The MemoryManager is responsible for reading the slice from the
TraceStore and persisting the result.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.logging import EventKind, TraceEvent

DEFAULT_COMPACTION_THRESHOLD = 200
"""Compact when an event slice grows past this size."""

PRESERVED_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.SESSION_STARTED,
        EventKind.SESSION_ENDED,
        EventKind.PLAN_PRODUCED,
        EventKind.TOOL_FAILED,
        EventKind.BRANCH_BACKTRACKED,
        EventKind.SKILL_REJECTED,
        EventKind.EVALUATION_PRODUCED,
        EventKind.OPTIMIZER_ACCEPTED,
    }
)
"""Event kinds always kept verbatim — the load-bearing audit trail."""


class CompactionTemplate(BaseModel):
    """Hermes-style structured summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str
    progress: str
    decisions: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


class CompactionResult(BaseModel):
    """Output of one compaction run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    range_start_event_id: str
    range_end_event_id: str
    summary: CompactionTemplate
    preserved_events: tuple[TraceEvent, ...] = ()
    compacted_event_count: int = Field(ge=0)


class EmptyCompactionRangeError(ValueError):
    """Raised when `compact()` is called on an empty event slice."""


class Compactor:
    """Stateless compactor.

    Construct once and reuse. `should_compact` is the gate the
    MemoryManager polls; `compact` runs the transformation.
    """

    def __init__(self, *, threshold: int = DEFAULT_COMPACTION_THRESHOLD) -> None:
        """Bind the size threshold above which compaction triggers."""
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold

    def should_compact(self, events: list[TraceEvent]) -> bool:
        """True when the slice is large enough to warrant compaction."""
        return len(events) >= self._threshold

    def compact(self, events: list[TraceEvent]) -> CompactionResult:
        """Collapse `events` into a structured summary.

        Args:
            events: Trace slice in insertion order. Must be non-empty
                and all from the same session.

        Returns:
            A `CompactionResult` summarising the slice while preserving
            the events listed in `PRESERVED_KINDS` verbatim.

        Raises:
            EmptyCompactionRangeError: If `events` is empty.
            ValueError: If events span more than one session.
        """
        if not events:
            raise EmptyCompactionRangeError("cannot compact an empty event slice")
        session_ids = {e.session_id for e in events}
        if len(session_ids) > 1:
            raise ValueError(f"compact() requires single-session input, got {sorted(session_ids)}")
        (session_id,) = session_ids

        preserved = tuple(e for e in events if e.kind in PRESERVED_KINDS)
        summary = _build_template(events)
        return CompactionResult(
            session_id=session_id,
            range_start_event_id=events[0].event_id,
            range_end_event_id=events[-1].event_id,
            summary=summary,
            preserved_events=preserved,
            compacted_event_count=len(events),
        )


def _build_template(events: list[TraceEvent]) -> CompactionTemplate:
    """Construct a deterministic structured template from `events`."""
    goal = _extract_goal(events)
    progress = _extract_progress(events)
    decisions = _extract_decisions(events)
    files = _extract_files(events)
    next_steps = _extract_next_steps(events)
    return CompactionTemplate(
        goal=goal,
        progress=progress,
        decisions=decisions,
        files=files,
        next_steps=next_steps,
    )


def _extract_goal(events: list[TraceEvent]) -> str:
    """Pull the user request from the first SESSION_STARTED, if any."""
    for e in events:
        if e.kind is EventKind.SESSION_STARTED:
            request = e.payload.get("user_request")
            if isinstance(request, str) and request:
                return request
    return "unknown"


def _extract_progress(events: list[TraceEvent]) -> str:
    """One-line histogram of event kinds and a tool success/failure count."""
    counts = Counter(e.kind for e in events)
    parts = [
        f"{counts.get(EventKind.PLAN_PRODUCED, 0)} plan",
        f"{counts.get(EventKind.BRANCH_SPAWNED, 0)} branches",
        f"{counts.get(EventKind.BRANCH_COMPLETED, 0)} completed",
        f"{counts.get(EventKind.BRANCH_BACKTRACKED, 0)} backtracked",
        f"{counts.get(EventKind.EVALUATION_PRODUCED, 0)} evaluations",
        f"{counts.get(EventKind.TOOL_FAILED, 0)} tool failures",
    ]
    return "; ".join(parts)


def _extract_decisions(events: list[TraceEvent]) -> tuple[str, ...]:
    """List evaluator verdicts in order — the durable decisions in a run."""
    out: list[str] = []
    for e in events:
        if e.kind is EventKind.EVALUATION_PRODUCED:
            verdict = e.payload.get("verdict") or "unknown"
            branch = e.branch_id or "?"
            out.append(f"{branch}: {verdict}")
        elif e.kind is EventKind.OPTIMIZER_ACCEPTED:
            out.append(f"optimizer accepted: {e.payload.get('candidate_id', '?')}")
    return tuple(out)


def _extract_files(events: list[TraceEvent]) -> tuple[str, ...]:
    """Collect file/path references mentioned in payloads (deduped)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for e in events:
        for value in _walk(e.payload):
            if (
                isinstance(value, str)
                and (value.endswith(".pdb") or value.endswith(".md"))
                and value not in seen_set
            ):
                seen.append(value)
                seen_set.add(value)
    return tuple(seen)


def _extract_next_steps(events: list[TraceEvent]) -> tuple[str, ...]:
    """If the slice ends with an unresolved iteration, list its open verdicts."""
    if not events or events[-1].kind is EventKind.SESSION_ENDED:
        return ()
    pending: list[str] = []
    for e in reversed(events):
        if e.kind is EventKind.ITERATION_FINISHED:
            verdict = e.payload.get("verdict")
            if isinstance(verdict, str) and verdict in {"retry", "branch"}:
                pending.append(f"continue iteration: {verdict}")
            break
    return tuple(pending)


def _walk(node: Any) -> list[Any]:
    """Yield every leaf value inside a nested dict/list/tuple."""
    out: list[Any] = []
    stack: list[Any] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        else:
            out.append(cur)
    return out

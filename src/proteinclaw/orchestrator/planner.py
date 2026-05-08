"""Planner: decompose a user request into a tuple of Tasks.

Phase 4 ships a heuristic planner — keyword matching against the user
request to pick a primary skill, then build a Task with reasonable default
success criteria. An optional `LLMClient` injection point is reserved for
Phase 4+, where the planner will instead ask the LLM for a structured plan.

The heuristic path keeps the end-to-end mocked test self-contained: no
LLM, no network, deterministic.
"""

from __future__ import annotations

from proteinclaw.common.llm import LLMClient
from proteinclaw.common.types import Comparison, Metric
from proteinclaw.orchestrator.task import (
    MAX_ITERATIONS_DEFAULT,
    SuccessCriterion,
    Task,
)


class Planner:
    """Builds tasks from a natural-language request.

    Inject an `LLMClient` when ready; without one, the heuristic path runs.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        """Construct with an optional LLM client (Phase 4+ wiring)."""
        self._llm = llm

    async def plan(self, *, user_request: str, session_id: str) -> tuple[Task, ...]:
        """Decompose `user_request` into Tasks.

        Args:
            user_request: Natural-language request from the user.
            session_id: Owning session.

        Returns:
            One or more Tasks. Order matters: the orchestrator dispatches
            them in order.
        """
        if self._llm is not None:
            # Phase 4+: structured-output prompt → tuple[Task, ...].
            # Falls through to the heuristic path until that lands.
            pass
        return self._heuristic_plan(user_request=user_request, session_id=session_id)

    def _heuristic_plan(self, *, user_request: str, session_id: str) -> tuple[Task, ...]:
        """Pick a task type from the request via keyword matching."""
        text = user_request.lower()
        if "binder" in text:
            return (_binder_task(user_request, session_id, text),)
        if "enzyme" in text or "stabili" in text:
            return (_enzyme_task(user_request, session_id, text),)
        if "motif" in text or "scaffold" in text:
            return (_motif_task(user_request, session_id, text),)
        if "hotspot" in text:
            return (_hotspot_task(user_request, session_id, text),)
        # Default: treat as binder design with no specific target. The
        # SubAgent picks a default target id when inputs are sparse.
        return (_binder_task(user_request, session_id, text),)


def _binder_task(request: str, session_id: str, lowered: str) -> Task:
    """Build a binder-design Task with default success criteria."""
    return Task(
        session_id=session_id,
        description=request,
        inputs={
            "task_type": "binder_design",
            "target_pdb_id": _extract_pdb_id(lowered),
        },
        success_criteria=(
            SuccessCriterion(
                name="confident_fold",
                metric=Metric.PLDDT,
                threshold=0.70,
                comparison=Comparison.GTE,
            ),
            SuccessCriterion(
                name="strong_pTM",
                metric=Metric.PTM,
                threshold=0.60,
                comparison=Comparison.GTE,
            ),
        ),
        max_iterations=MAX_ITERATIONS_DEFAULT,
    )


def _enzyme_task(request: str, session_id: str, lowered: str) -> Task:
    """Build an enzyme-design Task."""
    del lowered
    return Task(
        session_id=session_id,
        description=request,
        inputs={"task_type": "enzyme_design"},
        success_criteria=(
            SuccessCriterion(
                name="confident_fold",
                metric=Metric.PLDDT,
                threshold=0.75,
                comparison=Comparison.GTE,
            ),
        ),
    )


def _motif_task(request: str, session_id: str, lowered: str) -> Task:
    """Build a motif-scaffolding Task."""
    del lowered
    return Task(
        session_id=session_id,
        description=request,
        inputs={"task_type": "motif_scaffolding"},
        success_criteria=(
            SuccessCriterion(
                name="confident_fold",
                metric=Metric.PLDDT,
                threshold=0.70,
                comparison=Comparison.GTE,
            ),
        ),
    )


def _hotspot_task(request: str, session_id: str, lowered: str) -> Task:
    """Build a hotspot-selection Task."""
    del lowered
    return Task(
        session_id=session_id,
        description=request,
        inputs={"task_type": "hotspot_selection"},
        success_criteria=(
            SuccessCriterion(
                name="strong_pTM",
                metric=Metric.PTM,
                threshold=0.60,
                comparison=Comparison.GTE,
            ),
        ),
    )


def _extract_pdb_id(text: str) -> str:
    """Pull the first 4-character alphanumeric PDB-id-shaped token from `text`.

    Best-effort. Returns "1ABC" as a default when no candidate is found, so
    downstream tools always have something to chew on.
    """
    # PDB ids are 4 chars: digit + 3 alphanumeric. Strict regex keeps false
    # positives down on prose text.
    import re

    match = re.search(r"\b[0-9][A-Za-z0-9]{3}\b", text)
    return match.group(0).upper() if match else "1ABC"

"""Planner: decompose a user request into a tuple of Tasks.

Two paths:

- **LLM-driven** when an `LLMClient` is injected. The planner asks the
  model for a single structured `LLMPlan` (one task type + optional PDB
  id + criteria overrides) and converts it into our `Task` shape. If
  the LLM call or its output validation fails, we fall through to the
  heuristic path so the planner is never a hard dependency on the
  network.
- **Heuristic** when no client is available, or as the LLM fallback.
  Keyword matching picks the task type, regex extracts a PDB id.

The heuristic path keeps the end-to-end mocked test self-contained: no
LLM, no network, deterministic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.llm import LLMClient, Message
from proteinclaw.common.logging import get_logger
from proteinclaw.common.types import Comparison, Metric
from proteinclaw.orchestrator.task import (
    MAX_ITERATIONS_DEFAULT,
    SuccessCriterion,
    Task,
)

_log = get_logger(__name__)

_KNOWN_TASK_TYPES = {
    "binder_design",
    "enzyme_design",
    "motif_scaffolding",
    "hotspot_selection",
}


class _LLMSuccessCriterion(BaseModel):
    """Successful-criterion shape used in the LLM's structured response."""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: Metric
    threshold: float
    comparison: Comparison
    description: str = ""


class LLMPlan(BaseModel):
    """One task in the LLM's structured plan.

    Attributes:
        task_type: One of `_KNOWN_TASK_TYPES`. Anything else is dropped
            and (if no other tasks survive) the heuristic path takes over.
        target_pdb_id: Best-effort 4-character PDB id extracted from the
            request, or None.
        success_criteria: Optional overrides; falls back to defaults
            when empty.
        notes: Free-form rationale, surfaced in trace events but not
            otherwise consumed.
    """

    model_config = ConfigDict(extra="forbid")

    task_type: str
    target_pdb_id: str | None = None
    success_criteria: list[_LLMSuccessCriterion] = Field(default_factory=list)
    notes: str = ""


class LLMMultiTaskPlan(BaseModel):
    """The full structured response we ask Claude to produce.

    A multi-task plan is a list of `LLMPlan`s. The orchestrator dispatches
    them in order — earlier tasks complete (or fail gracefully) before
    later ones run. Phase 6.5 ships independent tasks: there's no
    automatic dependency injection, but the LLM can sequence them
    intentionally (e.g. ``hotspot_selection`` before ``binder_design``).

    Attributes:
        tasks: 1 to `MAX_TASKS_PER_PLAN` task plans, in execution order.
        notes: Free-form rationale at the plan level.
    """

    model_config = ConfigDict(extra="forbid")

    tasks: list[LLMPlan] = Field(default_factory=list)
    notes: str = ""


MAX_TASKS_PER_PLAN = 4
"""Cap on tasks per plan — keeps run cost bounded."""


_PLANNER_SYSTEM_PROMPT = (
    "You are the planner for ProteinClaw, a protein-design agent. "
    "Given a user request, emit a JSON object with a `tasks` field "
    "containing 1-4 task plans in execution order. Allowed task_type "
    "values per task: binder_design, enzyme_design, motif_scaffolding, "
    "hotspot_selection. Most requests need exactly ONE task; only "
    "decompose into multiple when the user describes a clearly multi-step "
    "workflow (e.g. 'pick hotspots then design a binder'). When in doubt, "
    "emit one task. If the user mentions a PDB id (4 alphanumeric "
    "characters), include it as target_pdb_id (uppercase). Use "
    "success_criteria sparingly — only when the user explicitly states a "
    "metric target."
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
            try:
                multi = await self._llm.complete_structured(
                    system=_PLANNER_SYSTEM_PROMPT,
                    messages=[Message(role="user", content=user_request)],
                    response_model=LLMMultiTaskPlan,
                )
            except Exception as e:
                _log.warning(
                    "planner.llm_failed",
                    error=str(e),
                    fallback="heuristic",
                )
                return self._heuristic_plan(user_request=user_request, session_id=session_id)
            tasks = self._tasks_from_multi_plan(multi, user_request, session_id)
            if tasks:
                return tasks
            _log.info("planner.llm_no_valid_tasks", task_count=len(multi.tasks))
        return self._heuristic_plan(user_request=user_request, session_id=session_id)

    def _tasks_from_multi_plan(
        self,
        multi: LLMMultiTaskPlan,
        user_request: str,
        session_id: str,
    ) -> tuple[Task, ...]:
        """Convert a multi-task plan to typed Tasks; drop unknown task types.

        Caps at `MAX_TASKS_PER_PLAN`. An empty result triggers fallback to
        the heuristic planner.
        """
        out: list[Task] = []
        for sub_plan in multi.tasks[:MAX_TASKS_PER_PLAN]:
            task = self._task_from_llm_plan(sub_plan, user_request, session_id)
            if task is not None:
                out.append(task)
            else:
                _log.info("planner.llm_dropped_task", task_type=sub_plan.task_type)
        return tuple(out)

    def _task_from_llm_plan(self, plan: LLMPlan, user_request: str, session_id: str) -> Task | None:
        """Convert a validated LLMPlan into a Task. Returns None on bad task_type."""
        if plan.task_type not in _KNOWN_TASK_TYPES:
            return None
        if plan.task_type == "binder_design":
            base = _binder_task(user_request, session_id, user_request.lower())
        elif plan.task_type == "enzyme_design":
            base = _enzyme_task(user_request, session_id, user_request.lower())
        elif plan.task_type == "motif_scaffolding":
            base = _motif_task(user_request, session_id, user_request.lower())
        else:  # hotspot_selection
            base = _hotspot_task(user_request, session_id, user_request.lower())
        update: dict[str, Any] = {}
        if plan.target_pdb_id:
            update["inputs"] = {**base.inputs, "target_pdb_id": plan.target_pdb_id.upper()}
        if plan.success_criteria:
            update["success_criteria"] = tuple(
                SuccessCriterion(
                    name=c.name,
                    metric=c.metric,
                    threshold=c.threshold,
                    comparison=c.comparison,
                    description=c.description,
                )
                for c in plan.success_criteria
            )
        return base.model_copy(update=update) if update else base

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
    criteria = [
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
        SuccessCriterion(
            name="binder_monomer_confident",
            metric=Metric.BINDER_MONOMER_CONFIDENCE,
            threshold=0.70,
            comparison=Comparison.GTE,
        ),
        SuccessCriterion(
            name="complex_confident",
            metric=Metric.COMPLEX_CONFIDENCE,
            threshold=0.30,
            comparison=Comparison.GTE,
        ),
        SuccessCriterion(
            name="interface_contacts_present",
            metric=Metric.INTERFACE_CONTACTS,
            threshold=8.0,
            comparison=Comparison.GTE,
        ),
        SuccessCriterion(
            name="interface_burial",
            metric=Metric.INTERFACE_SASA,
            threshold=300.0,
            comparison=Comparison.GTE,
        ),
        SuccessCriterion(
            name="low_interface_clashes",
            metric=Metric.CLASH_SCORE,
            threshold=5.0,
            comparison=Comparison.LTE,
        ),
        SuccessCriterion(
            name="binder_reaches_target",
            metric=Metric.TARGET_BINDER_MIN_DISTANCE,
            threshold=5.0,
            comparison=Comparison.LTE,
        ),
    ]
    if "hotspot" in lowered:
        criteria.append(
            SuccessCriterion(
                name="hotspot_contacts",
                metric=Metric.HOTSPOT_SATISFACTION,
                threshold=0.60,
                comparison=Comparison.GTE,
            )
        )
    return Task(
        session_id=session_id,
        description=request,
        inputs={
            "task_type": "binder_design",
            "target_pdb_id": _extract_pdb_id(lowered),
        },
        success_criteria=tuple(criteria),
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

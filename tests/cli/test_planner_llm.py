"""Tests for the LLM-driven path in orchestrator/planner.py."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from proteinclaw.common.llm import Message
from proteinclaw.common.types import Comparison, Metric
from proteinclaw.orchestrator.planner import LLMMultiTaskPlan, LLMPlan, Planner


class _ScriptedLLM:
    """Stub LLMClient that returns canned structured responses.

    Pass either ``plan=`` (single-task, wrapped as a multi-task plan) or
    ``multi_plan=`` (full multi-task plan) — never both.
    """

    def __init__(
        self,
        *,
        plan: LLMPlan | None = None,
        multi_plan: LLMMultiTaskPlan | None = None,
        raises: Exception | None = None,
    ) -> None:
        if plan is not None and multi_plan is not None:
            raise ValueError("pass plan OR multi_plan, not both")
        if plan is not None:
            multi_plan = LLMMultiTaskPlan(tasks=[plan])
        self._multi = multi_plan
        self._raises = raises
        self.calls = 0

    async def complete(self, *, system: str | None, messages: Sequence[Message]) -> str:
        del system, messages
        return ""

    async def complete_structured(
        self,
        *,
        system: str | None,
        messages: Sequence[Message],
        response_model: type,
    ) -> object:
        del system, messages, response_model
        self.calls += 1
        if self._raises:
            raise self._raises
        assert self._multi is not None
        return self._multi


async def test_llm_plan_produces_typed_task() -> None:
    llm = _ScriptedLLM(
        plan=LLMPlan(
            task_type="binder_design",
            target_pdb_id="2XYZ",
        )
    )
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="design a binder for 2XYZ", session_id="s"
    )
    assert llm.calls == 1
    assert len(tasks) == 1
    assert tasks[0].inputs["task_type"] == "binder_design"
    assert tasks[0].inputs["target_pdb_id"] == "2XYZ"


async def test_llm_plan_overrides_success_criteria() -> None:
    from proteinclaw.orchestrator.planner import _LLMSuccessCriterion

    llm = _ScriptedLLM(
        plan=LLMPlan(
            task_type="binder_design",
            target_pdb_id="1ABC",
            success_criteria=[
                _LLMSuccessCriterion(
                    name="strict_plddt",
                    metric=Metric.PLDDT,
                    threshold=0.95,
                    comparison=Comparison.GTE,
                )
            ],
        )
    )
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="design a binder, want pLDDT 0.95+", session_id="s"
    )
    criteria = tasks[0].success_criteria
    assert len(criteria) == 1
    assert criteria[0].threshold == 0.95


async def test_llm_failure_falls_back_to_heuristic() -> None:
    llm = _ScriptedLLM(raises=RuntimeError("api down"))
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="design a binder for 1ABC", session_id="s"
    )
    # heuristic still produces a binder task
    assert tasks[0].inputs["task_type"] == "binder_design"
    assert tasks[0].inputs["target_pdb_id"] == "1ABC"


async def test_llm_unknown_task_type_falls_back_to_heuristic() -> None:
    llm = _ScriptedLLM(plan=LLMPlan(task_type="banana_design"))
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="enzyme stability", session_id="s"
    )
    # heuristic picks enzyme_design from "enzyme stability"
    assert tasks[0].inputs["task_type"] == "enzyme_design"


async def test_no_llm_uses_heuristic() -> None:
    tasks = await Planner().plan(user_request="motif scaffolding for X", session_id="s")
    assert tasks[0].inputs["task_type"] == "motif_scaffolding"


@pytest.mark.parametrize(
    "task_type",
    ["binder_design", "enzyme_design", "motif_scaffolding", "hotspot_selection"],
)
async def test_llm_produces_each_known_task_type(task_type: str) -> None:
    llm = _ScriptedLLM(plan=LLMPlan(task_type=task_type))
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="anything", session_id="s"
    )
    assert tasks[0].inputs["task_type"] == task_type


async def test_llm_multi_task_plan_emits_each_in_order() -> None:
    """Decompose 'pick hotspots then design a binder' into two tasks."""
    llm = _ScriptedLLM(
        multi_plan=LLMMultiTaskPlan(
            tasks=[
                LLMPlan(task_type="hotspot_selection", target_pdb_id="1ABC"),
                LLMPlan(task_type="binder_design", target_pdb_id="1ABC"),
            ]
        )
    )
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="select hotspots on 1ABC then design a binder",
        session_id="s",
    )
    assert len(tasks) == 2
    assert [t.inputs["task_type"] for t in tasks] == [
        "hotspot_selection",
        "binder_design",
    ]
    assert all(t.inputs["target_pdb_id"] == "1ABC" for t in tasks)


async def test_llm_drops_unknown_task_types_keeps_valid_ones() -> None:
    """Mixed valid + invalid tasks: invalid drop, valid survive."""
    llm = _ScriptedLLM(
        multi_plan=LLMMultiTaskPlan(
            tasks=[
                LLMPlan(task_type="banana_design"),  # bogus
                LLMPlan(task_type="binder_design"),
            ]
        )
    )
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="anything", session_id="s"
    )
    assert len(tasks) == 1
    assert tasks[0].inputs["task_type"] == "binder_design"


async def test_llm_all_unknown_falls_back_to_heuristic() -> None:
    """If every emitted task type is unknown, the heuristic takes over."""
    llm = _ScriptedLLM(
        multi_plan=LLMMultiTaskPlan(
            tasks=[
                LLMPlan(task_type="banana_design"),
                LLMPlan(task_type="apple_design"),
            ]
        )
    )
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="design a binder for 1ABC", session_id="s"
    )
    # Heuristic kicks in.
    assert len(tasks) == 1
    assert tasks[0].inputs["task_type"] == "binder_design"


async def test_llm_caps_at_max_tasks() -> None:
    """More than MAX_TASKS_PER_PLAN entries are truncated."""
    from proteinclaw.orchestrator.planner import MAX_TASKS_PER_PLAN

    over_cap = [LLMPlan(task_type="binder_design")] * (MAX_TASKS_PER_PLAN + 3)
    llm = _ScriptedLLM(multi_plan=LLMMultiTaskPlan(tasks=over_cap))
    tasks = await Planner(llm=llm).plan(  # type: ignore[arg-type]
        user_request="x", session_id="s"
    )
    assert len(tasks) == MAX_TASKS_PER_PLAN

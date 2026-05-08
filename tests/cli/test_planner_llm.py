"""Tests for the LLM-driven path in orchestrator/planner.py."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from proteinclaw.common.llm import Message
from proteinclaw.common.types import Comparison, Metric
from proteinclaw.orchestrator.planner import LLMPlan, Planner


class _ScriptedLLM:
    """Stub LLMClient that returns canned structured responses."""

    def __init__(self, *, plan: LLMPlan | None = None, raises: Exception | None = None) -> None:
        self._plan = plan
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
        assert self._plan is not None
        return self._plan


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

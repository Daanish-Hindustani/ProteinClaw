"""Tests for agents/llm_executor.py and the SubAgent's LLM-driven path."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from proteinclaw.agents.branch_result import BranchStatus
from proteinclaw.agents.llm_executor import (
    AgentAction,
    LLMExecutor,
    _format_observations,
    _Observation,
    _promote_best_child_outputs,
    _summarize,
)
from proteinclaw.agents.permissions import ToolPermissionSet
from proteinclaw.agents.sub_agent import BranchParams, SubAgent
from proteinclaw.common.llm import Message
from proteinclaw.memory.trace_store import InMemoryTraceStore
from proteinclaw.orchestrator.task import Task
from proteinclaw.skills.skill import Skill, SkillProvenance
from proteinclaw.skills.skill_library import SkillLibrary
from proteinclaw.tools.protein.alphafold import AlphaFold
from proteinclaw.tools.protein.foldseek import Foldseek
from proteinclaw.tools.protein.protein_mpnn import ProteinMPNN
from proteinclaw.tools.protein.rcsb import RCSB
from proteinclaw.tools.protein.rfdiffusion3 import RFDiffusion3
from proteinclaw.tools.registry import ToolRegistry


class _ScriptedActionLLM:
    """Stub LLMClient that returns a fixed sequence of AgentActions."""

    def __init__(self, *, actions: Sequence[AgentAction]) -> None:
        self._queue: list[AgentAction] = list(actions)
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
        if not self._queue:
            raise AssertionError("LLM ran out of canned actions")
        return self._queue.pop(0)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool in (RCSB(), RFDiffusion3(), ProteinMPNN(), AlphaFold(), Foldseek()):
        reg.register(tool)
    return reg


def _binder_skill() -> Skill:
    return Skill(
        id="binder_design",
        version=1,
        name="Binder",
        description="design binders",
        applicable_tasks=("binder_design",),
        body="Step 1. fetch target. Step 2. generate backbone. Step 3. design seq. "
        "Step 4. fold. Step 5. novelty.",
        provenance=SkillProvenance.HUMAN_AUTHORED,
    )


def _library() -> SkillLibrary:
    lib = SkillLibrary()
    lib.add(_binder_skill())
    return lib


def _hotspot_skill() -> Skill:
    return Skill(
        id="hotspot_selection",
        version=1,
        name="Hotspot Selection",
        description="select binding hotspots",
        applicable_tasks=("hotspot_selection",),
        body="Pick exposed target residues.",
        provenance=SkillProvenance.HUMAN_AUTHORED,
    )


def _multi_skill_library() -> SkillLibrary:
    lib = _library()
    lib.add(_hotspot_skill())
    return lib


def _binder_task() -> Task:
    return Task(
        session_id="s1",
        description="Design a binder for 1ABC",
        inputs={"task_type": "binder_design", "target_pdb_id": "1ABC"},
    )


# --- LLMExecutor unit tests ----------------------------------------------


async def test_executor_runs_full_pipeline_when_llm_drives_it() -> None:
    """LLM walks rcsb → rfdiffusion3 → protein_mpnn → alphafold → foldseek → finish."""
    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}, reasoning="fetch target"),
        AgentAction(
            tool_name="rfdiffusion3",
            inputs={
                "target_pdb_path": "1ABC",
                "contigs": "10-20/A1-50/30-40",
                "num_designs": 2,
            },
            reasoning="generate backbones",
        ),
        AgentAction(
            tool_name="protein_mpnn",
            inputs={"backbone_pdb_path": "/mock/bb.pdb", "num_sequences": 2},
            reasoning="design sequences",
        ),
        AgentAction(
            tool_name="alphafold",
            inputs={"sequence": "MKVLAVAGAATG", "msa": None},
            reasoning="fold",
        ),
        AgentAction(
            tool_name="foldseek",
            inputs={"query_pdb_path": "/mock/fold.pdb", "max_hits": 5},
            reasoning="novelty",
        ),
        AgentAction(finish=True, summary="all metrics computed"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    # Each tool emits its own payload key, plus the alphafold mirror at "fold".
    assert {"rcsb", "rfdiffusion3", "protein_mpnn", "alphafold", "fold", "foldseek"} <= set(
        result.payload
    )
    # Mirror is identical content to the alphafold key.
    assert result.payload["fold"] == result.payload["alphafold"]


async def test_executor_finishes_immediately_when_llm_says_so() -> None:
    actions = [AgentAction(finish=True, summary="nothing to do")]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    assert result.payload == {}


async def test_subagent_falls_back_to_task_type_when_llm_skill_picker_fails() -> None:
    """A malformed skill-picker response should not kill structured binder tasks."""

    class _FallbackLLM:
        def __init__(self) -> None:
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
            if self.calls == 1:
                raise RuntimeError("empty skill picker response")
            return AgentAction(finish=True, summary="selected by task_type fallback")

    llm = _FallbackLLM()
    sub = SubAgent(
        registry=_registry(),
        skill_library=_multi_skill_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )

    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )

    assert result.status is BranchStatus.COMPLETED
    assert result.skill_version_id == "binder_design@v1"
    assert llm.calls == 2


async def test_executor_repeat_cap_records_observation_and_lets_llm_continue() -> None:
    """Hitting the repeat cap is now a recoverable observation, not a hard stop."""
    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),
        # Third rcsb hits the cap — observation recorded, LLM gets another turn.
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),
        AgentAction(finish=True, summary="moved on after cap"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    # Two successful rcsb calls landed; the third was capped (no payload added).
    assert "rcsb" in result.payload
    # LLM was asked four times (3 attempts + final finish).
    assert llm.calls == 4


async def test_executor_tool_failure_emits_tool_failed_event() -> None:
    """Tool failures are now within-branch observations + a TOOL_FAILED trace event."""
    trace = InMemoryTraceStore()
    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "TOOLONG"}),  # validation error
        AgentAction(finish=True, summary="gave up gracefully"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=trace,
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    # Branch completes — the failure didn't bubble up.
    assert result.status is BranchStatus.COMPLETED
    # A TOOL_FAILED trace event was emitted for the bad call.
    events = await trace.read_session("s1")
    assert any(e.kind.value == "tool.failed" for e in events)


async def test_executor_max_steps_terminates_cleanly() -> None:
    """Hitting max_steps without finish=True ends the branch successfully."""
    # Two distinct tools so the repeat cap doesn't fire first.
    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),
        AgentAction(
            tool_name="rfdiffusion3",
            inputs={
                "target_pdb_path": "1ABC",
                "contigs": "A1-50",
            },
        ),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
        max_steps=2,
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    assert {"rcsb", "rfdiffusion3"} <= set(result.payload)


async def test_executor_action_without_tool_or_finish_stops() -> None:
    """An LLM emitting neither tool_name nor finish=True ends the branch."""
    actions = [AgentAction()]  # both empty
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED  # not FAILED — clean stop


async def test_heuristic_path_unchanged_when_no_llm() -> None:
    """Sub-agent without LLM keeps the original deterministic pipeline."""
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
    )  # no llm
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    assert {"rcsb", "rfdiffusion3", "protein_mpnn", "fold", "foldseek"} <= set(result.payload)


# --- Helper coverage ------------------------------------------------------


def test_format_observations_handles_empty_and_truncates() -> None:
    assert _format_observations([]) == "(none yet)"
    # Long list of small ints expands fully when it fits in budget. With
    # 50 items of ~3 chars each (~150 chars total) the inline form fits.
    obs = _Observation(tool_name="x", payload={"hits": list(range(50))})
    rendered = _format_observations([obs])
    assert "0, 1, 2" in rendered and "49" in rendered
    # A list big enough to exceed the budget still falls back to "+N more"
    # so we don't blow up the LLM prompt with thousands of items.
    huge = _Observation(tool_name="x", payload={"hits": ["x" * 200] * 50})
    rendered_huge = _format_observations([huge])
    assert "+49 more" in rendered_huge


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("short", "short"),
        # 120-char string-truncation threshold (raised from 80) keeps
        # binder-length sequences and full PDB paths visible inline.
        ("a" * 100, "a" * 100),
        ("a" * 200, "a" * 117 + "..."),
        # Lists fully expand when their inline form fits in the budget;
        # the LLM needs to see all designed sequences / fold candidates
        # to pick the best by index without re-reading FASTA files.
        ([1, 2, 3], "[1, 2, 3]"),
        ((1,), "[1]"),
        # Small dicts render inline so paths/ids reach the LLM.
        ({"k": "v"}, "{k=v}"),
        (42, "42"),
    ],
)
def test_summarize_branches(value: object, expected: str) -> None:
    assert _summarize(value) == expected


async def test_executor_emits_step_trace_events() -> None:
    """Each LLM step appends an OPTIMIZER_STEP event."""
    trace = InMemoryTraceStore()
    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}, reasoning="r1"),
        AgentAction(finish=True, summary="ok"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    executor = LLMExecutor(
        llm=llm,  # type: ignore[arg-type]
        registry=_registry(),
        trace_store=trace,
    )
    await executor.run(
        task_description="design",
        skill=_binder_skill(),
        session_id="s1",
        branch_id="b1",
        task_inputs={"target_pdb_id": "1ABC"},
    )
    events = await trace.read_branch("b1")
    optimizer_steps = [e for e in events if e.kind.value == "evolution.optimizer_step"]
    assert len(optimizer_steps) == 2  # one per LLM action


# --- Within-branch backtrack on tool failure -----------------------------


async def test_executor_tool_failure_recorded_as_observation_then_recovers() -> None:
    """The LLM picks a different tool after seeing the failure observation."""
    from proteinclaw.agents.llm_executor import AgentAction

    actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "TOOLONG"}),  # input invalid → fails
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),  # retry with valid
        AgentAction(finish=True, summary="recovered"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    # Branch completes — failure didn't bubble up.
    assert result.status is BranchStatus.COMPLETED
    # The valid second call landed in the payload.
    assert "rcsb" in result.payload


# --- Success criteria surfacing ------------------------------------------


async def test_executor_passes_success_criteria_to_llm() -> None:
    """The criteria block ends up in the user message the LLM sees."""
    from proteinclaw.agents.llm_executor import AgentAction
    from proteinclaw.common.types import Comparison, Metric
    from proteinclaw.orchestrator.task import SuccessCriterion

    seen_messages: list[str] = []

    class _CapturingLLM:
        async def complete(self, *, system, messages):  # type: ignore[no-untyped-def]
            del system, messages
            return ""

        async def complete_structured(  # type: ignore[no-untyped-def]
            self, *, system, messages, response_model
        ):
            del system, response_model
            seen_messages.append(messages[0].content)
            return AgentAction(finish=True, summary="done")

    executor = LLMExecutor(
        llm=_CapturingLLM(),
        registry=_registry(),
        trace_store=InMemoryTraceStore(),
    )
    await executor.run(
        task_description="design a binder",
        skill=_binder_skill(),
        session_id="s1",
        branch_id="b1",
        task_inputs={"target_pdb_id": "1ABC"},
        success_criteria=(
            SuccessCriterion(
                name="confident_fold",
                metric=Metric.PLDDT,
                threshold=0.8,
                comparison=Comparison.GTE,
            ),
        ),
    )
    assert seen_messages
    msg = seen_messages[0]
    assert "Success criteria" in msg
    assert "confident_fold" in msg
    assert "plddt" in msg


# --- Child sub-agent delegation ------------------------------------------


async def test_executor_delegate_action_spawns_child_with_payload_merged() -> None:
    """LLM emits a delegate action; child payload lands under `child_1`."""
    from proteinclaw.agents.llm_executor import AgentAction, DelegateRequest

    actions = [
        AgentAction(
            delegate=DelegateRequest(
                description="select hotspots on 1ABC",
                skill_id="binder_design",  # any registered skill is fine
            ),
            reasoning="need hotspots first",
        ),
        AgentAction(finish=True, summary="have child output"),
    ]
    llm = _ScriptedActionLLM(actions=actions)

    # Stub the spawn callback: simulate child returning a payload directly.
    spawned: list[DelegateRequest] = []

    async def fake_spawn(
        request: DelegateRequest,
        *,
        parent_payload: dict[str, Any],
        parent_observations: Sequence[_Observation],
    ) -> dict[str, Any]:
        del parent_payload, parent_observations  # accepted but unused in this stub
        spawned.append(request)
        return {"hotspots": ["A45", "A46"]}

    executor = LLMExecutor(
        llm=llm,  # type: ignore[arg-type]
        registry=_registry(),
        trace_store=InMemoryTraceStore(),
    )
    result = await executor.run(
        task_description="design",
        skill=_binder_skill(),
        session_id="s1",
        branch_id="b1",
        task_inputs={},
        spawn_child=fake_spawn,
    )
    assert spawned and spawned[0].description == "select hotspots on 1ABC"
    assert "child_1" in result.payload
    assert result.payload["child_1"] == {"hotspots": ["A45", "A46"]}


def test_promote_best_child_outputs_surfaces_fold_metrics() -> None:
    payload: dict[str, Any] = {
        "rfdiffusion3": {"designs": [{"design_id": "0"}]},
        "child_1": {
            "protein_mpnn": {"sequences": [{"sequence": "AAA", "score": 1.0}]},
            "fold": {"pdb_path": "/tmp/low.pdb", "plddt": 0.72, "ptm": 0.71},
        },
        "child_2": {
            "protein_mpnn": {"sequences": [{"sequence": "BBB", "score": 0.8}]},
            "fold": {"pdb_path": "/tmp/high.pdb", "plddt": 0.91, "ptm": 0.82},
        },
    }

    _promote_best_child_outputs(payload)

    assert payload["fold"] == {"pdb_path": "/tmp/high.pdb", "plddt": 0.91, "ptm": 0.82}
    assert payload["protein_mpnn"] == {"sequences": [{"sequence": "BBB", "score": 0.8}]}


async def test_executor_delegate_without_spawner_records_observation() -> None:
    """When delegation is denied, the LLM gets an observation, not a crash."""
    from proteinclaw.agents.llm_executor import AgentAction, DelegateRequest

    actions = [
        AgentAction(
            delegate=DelegateRequest(description="impossible sub-task"),
        ),
        AgentAction(finish=True, summary="couldn't delegate"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    executor = LLMExecutor(
        llm=llm,  # type: ignore[arg-type]
        registry=_registry(),
        trace_store=InMemoryTraceStore(),
    )
    result = await executor.run(
        task_description="x",
        skill=_binder_skill(),
        session_id="s1",
        branch_id="b1",
        task_inputs={},
        # no spawn_child
    )
    # Branch completes cleanly; the delegation just didn't happen.
    assert result.finished_explicitly is True
    assert all(not k.startswith("child_") for k in result.payload)


async def test_executor_stops_repeated_delegate_when_spawner_missing() -> None:
    """Cheap models should not burn the full budget repeating invalid delegates."""
    from proteinclaw.agents.llm_executor import AgentAction, DelegateRequest

    actions = [
        AgentAction(delegate=DelegateRequest(description="first invalid delegate")),
        AgentAction(delegate=DelegateRequest(description="second invalid delegate")),
        AgentAction(finish=True, summary="would be too late"),
    ]
    llm = _ScriptedActionLLM(actions=actions)
    executor = LLMExecutor(
        llm=llm,  # type: ignore[arg-type]
        registry=_registry(),
        trace_store=InMemoryTraceStore(),
    )

    result = await executor.run(
        task_description="x",
        skill=_binder_skill(),
        session_id="s1",
        branch_id="b1",
        task_inputs={},
    )

    assert result.steps_taken == 2
    assert result.finished_explicitly is False
    assert "repeated delegate" in result.finish_summary


async def test_subagent_child_runs_with_child_permissions_at_depth_1() -> None:
    """End-to-end: parent delegates; child runs with `can_delegate=False`."""
    from proteinclaw.agents.branching_service import BranchBudget
    from proteinclaw.agents.llm_executor import AgentAction, DelegateRequest

    parent_actions = [
        AgentAction(
            delegate=DelegateRequest(description="quick sub-task"),
            reasoning="delegating",
        ),
        AgentAction(finish=True, summary="done"),
    ]
    child_actions = [
        AgentAction(tool_name="rcsb", inputs={"pdb_id": "1ABC"}),
        AgentAction(finish=True, summary="child done"),
    ]
    # Combined queue: parent's actions are interleaved across the run because
    # the parent invokes the child synchronously. The order is parent[0],
    # child[0], child[1], parent[1].
    queued = [parent_actions[0], child_actions[0], child_actions[1], parent_actions[1]]
    llm = _ScriptedActionLLM(actions=queued)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    budget = BranchBudget(cap=4)
    budget.reserve()  # parent
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
        budget=budget,
    )
    assert result.status is BranchStatus.COMPLETED
    # Parent's payload contains a child_1 key with the child's rcsb output.
    assert "child_1" in result.payload
    assert "rcsb" in result.payload["child_1"]


async def test_branch_budget_blocks_overflow_delegation() -> None:
    """When the budget is exhausted, delegate fails as an observation, not a crash."""
    from proteinclaw.agents.branching_service import BranchBudget
    from proteinclaw.agents.llm_executor import AgentAction, DelegateRequest

    parent_actions = [
        AgentAction(delegate=DelegateRequest(description="sub")),
        AgentAction(finish=True, summary="ok"),
    ]
    llm = _ScriptedActionLLM(actions=parent_actions)
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=llm,  # type: ignore[arg-type]
    )
    budget = BranchBudget(cap=1)
    budget.reserve()  # parent fills the budget
    result = await sub.run(
        task=_binder_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
        budget=budget,
    )
    assert result.status is BranchStatus.COMPLETED
    assert all(not k.startswith("child_") for k in result.payload)


async def test_child_cannot_delegate_further() -> None:
    """A depth=1 child gets spawn_child=None even with budget left."""
    from proteinclaw.agents.branching_service import BranchBudget

    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
        llm=_ScriptedActionLLM(actions=[]),  # type: ignore[arg-type]
    )
    builder = sub._build_spawn_child(
        parent_task=_binder_task(),
        parent_branch_id="b1",
        depth=1,  # child level
        permissions=ToolPermissionSet.child(),
        budget=BranchBudget(cap=10),
    )
    assert builder is None  # child can't recursively delegate

"""End-to-end integration test for Phase 4.

Builds the full stack with mocked protein-design tools and runs a binder
prompt through the orchestrator. Asserts on the trace replay (every step
emits the expected events) and on the finalized session shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.agents.branching_service import (
    MAX_FANOUT,
    BranchingService,
)
from proteinclaw.agents.sub_agent import SubAgent
from proteinclaw.common.logging import EventKind
from proteinclaw.evaluation.evaluator import EvaluationConfig, Evaluator
from proteinclaw.memory.session_store import InMemorySessionStore
from proteinclaw.memory.trace_store import InMemoryTraceStore
from proteinclaw.orchestrator.orchestrator import MAX_ITERATIONS, Orchestrator
from proteinclaw.orchestrator.planner import Planner
from proteinclaw.skills.skill_library import SkillLibrary
from proteinclaw.tools.protein.alphafold import AlphaFold
from proteinclaw.tools.protein.foldseek import Foldseek
from proteinclaw.tools.protein.protein_mpnn import ProteinMPNN
from proteinclaw.tools.protein.rcsb import RCSB
from proteinclaw.tools.protein.rfdiffusion3 import RFDiffusion3
from proteinclaw.tools.registry import ToolRegistry


@pytest.mark.integration
async def test_end_to_end_mocked_binder_run() -> None:
    # --- Build the full stack -------------------------------------------------
    repo_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240 — sync filesystem read at fixture time
    seeds = repo_root / "src" / "proteinclaw" / "skills" / "protein_design"
    config_yaml = repo_root / "config" / "evaluation.yaml"

    registry = ToolRegistry()
    for tool in (RCSB(), RFDiffusion3(), ProteinMPNN(), AlphaFold(), Foldseek()):
        registry.register(tool)
    library = SkillLibrary.from_directory(seeds)
    trace_store = InMemoryTraceStore()
    session_store = InMemorySessionStore()

    sub_agent = SubAgent(registry=registry, skill_library=library, trace_store=trace_store)
    branching = BranchingService(sub_agent=sub_agent, trace_store=trace_store)
    evaluator = Evaluator(
        name="default",
        config=EvaluationConfig.from_yaml(config_yaml),
    )
    orchestrator = Orchestrator(
        planner=Planner(),
        branching_service=branching,
        evaluator=evaluator,
        session_store=session_store,
        trace_store=trace_store,
    )

    # --- Run -----------------------------------------------------------------
    final = await orchestrator.run("Design a binder for PDB 1ABC")

    # --- Session-level invariants --------------------------------------------
    assert final.user_request == "Design a binder for PDB 1ABC"
    assert final.ended_at is not None
    assert final.final_payload is not None
    assert len(final.task_ids) >= 1
    # Iteration cap holds across all tasks combined; with one task and
    # k=3 the upper bound is 3.
    assert final.iterations_used <= MAX_ITERATIONS * len(final.task_ids)
    assert final.active_branch_ids == ()  # finalized clears these

    # --- Trace replay: required event kinds ----------------------------------
    events = await trace_store.read_session(final.session_id)
    kinds = [e.kind for e in events]
    for required in (
        EventKind.SESSION_STARTED,
        EventKind.REQUEST_RECEIVED,
        EventKind.PLAN_PRODUCED,
        EventKind.ITERATION_STARTED,
        EventKind.BRANCH_SPAWNED,
        EventKind.SKILL_SELECTED,
        EventKind.BRANCH_COMPLETED,
        EventKind.EVALUATION_PRODUCED,
        EventKind.ITERATION_FINISHED,
        EventKind.SESSION_ENDED,
    ):
        assert required in kinds, f"missing event kind in trace: {required}"

    # --- branches spawned in multiples of MAX_FANOUT ------------------------
    spawn_events = [e for e in events if e.kind is EventKind.BRANCH_SPAWNED]
    # MAX_FANOUT was lowered to 1 to control wall clock; we still require
    # at least one root branch and that the count divides cleanly so a
    # bumped MAX_FANOUT keeps this assertion meaningful.
    assert len(spawn_events) >= 1
    assert len(spawn_events) % MAX_FANOUT == 0

    # --- Final payload shape -------------------------------------------------
    assert "tasks" in final.final_payload
    assert len(final.final_payload["tasks"]) == len(final.task_ids)
    for t in final.final_payload["tasks"]:
        assert "winner_branch_id" in t
        assert "verdict" in t

    # --- Trace ordering: SESSION_STARTED first, SESSION_ENDED last -----------
    assert events[0].kind is EventKind.SESSION_STARTED
    assert events[-1].kind is EventKind.SESSION_ENDED


@pytest.mark.integration
async def test_iteration_cap_respected_when_no_success() -> None:
    """If criteria are unreachable, the orchestrator runs exactly k=3 iterations."""
    repo_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240 — sync filesystem read at fixture time
    seeds = repo_root / "src" / "proteinclaw" / "skills" / "protein_design"

    registry = ToolRegistry()
    for tool in (RCSB(), RFDiffusion3(), ProteinMPNN(), AlphaFold(), Foldseek()):
        registry.register(tool)
    library = SkillLibrary.from_directory(seeds)
    trace_store = InMemoryTraceStore()
    session_store = InMemorySessionStore()

    sub_agent = SubAgent(registry=registry, skill_library=library, trace_store=trace_store)
    branching = BranchingService(sub_agent=sub_agent, trace_store=trace_store)

    # Force unreachable thresholds → no STOP_SUCCESS verdict possible.
    impossible = EvaluationConfig(defaults={}, retry_floor=0.5)
    evaluator = Evaluator(name="strict", config=impossible)

    # Force-build a task whose thresholds the mocks can never meet.
    from proteinclaw.common.types import Comparison, Metric
    from proteinclaw.orchestrator.task import SuccessCriterion, Task

    impossible_task = Task(
        session_id="forced",
        description="binder",
        inputs={"task_type": "binder_design", "target_pdb_id": "1ABC"},
        success_criteria=(
            SuccessCriterion(
                name="impossible_plddt",
                metric=Metric.PLDDT,
                threshold=99.0,
                comparison=Comparison.GTE,
            ),
        ),
    )

    # Plug the impossible task in via a one-shot planner stub.
    class _StubPlanner(Planner):
        async def plan(  # type: ignore[override]
            self, *, user_request: str, session_id: str
        ) -> tuple[Task, ...]:
            return (
                Task(
                    session_id=session_id,
                    description=user_request,
                    inputs=impossible_task.inputs,
                    success_criteria=impossible_task.success_criteria,
                ),
            )

    orchestrator = Orchestrator(
        planner=_StubPlanner(),
        branching_service=branching,
        evaluator=evaluator,
        session_store=session_store,
        trace_store=trace_store,
    )
    final = await orchestrator.run("force the impossible")
    iteration_started_events = [
        e
        for e in await trace_store.read_session(final.session_id)
        if e.kind is EventKind.ITERATION_STARTED
    ]
    assert len(iteration_started_events) == MAX_ITERATIONS
    assert final.iterations_used == MAX_ITERATIONS

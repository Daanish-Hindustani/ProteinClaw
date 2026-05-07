"""Tests for agents/branching_service.py — caps, parallel spawn, trace events."""

from __future__ import annotations

import pytest

from proteinclaw.agents.branch_result import BranchStatus
from proteinclaw.agents.branching_service import (
    MAX_FANOUT,
    BranchBudgetExceededError,
    BranchingService,
)
from proteinclaw.agents.sub_agent import SubAgent
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


def _setup() -> tuple[BranchingService, InMemoryTraceStore]:
    reg = ToolRegistry()
    for tool in (RCSB(), RFDiffusion3(), ProteinMPNN(), AlphaFold(), Foldseek()):
        reg.register(tool)
    lib = SkillLibrary()
    lib.add(
        Skill(
            id="binder_design",
            version=1,
            name="Binder",
            description="d",
            applicable_tasks=("binder_design",),
            body="Step 1.",
            provenance=SkillProvenance.HUMAN_AUTHORED,
        )
    )
    trace = InMemoryTraceStore()
    sub = SubAgent(registry=reg, skill_library=lib, trace_store=trace)
    return BranchingService(sub_agent=sub, trace_store=trace), trace


def _task() -> Task:
    return Task(
        session_id="s1",
        description="binder",
        inputs={"task_type": "binder_design", "target_pdb_id": "1ABC"},
    )


async def test_explore_default_fanout_yields_three_branches() -> None:
    service, _ = _setup()
    results = await service.explore(task=_task())
    assert len(results) == MAX_FANOUT
    assert all(r.status is BranchStatus.COMPLETED for r in results)


async def test_explore_clamps_fanout_above_max() -> None:
    service, _ = _setup()
    results = await service.explore(task=_task(), fanout=99)
    assert len(results) == MAX_FANOUT


async def test_explore_emits_one_spawn_event_per_branch() -> None:
    service, trace = _setup()
    await service.explore(task=_task())
    events = await trace.read_session("s1")
    spawn_events = [e for e in events if e.kind.value == "agent.branch_spawned"]
    assert len(spawn_events) == MAX_FANOUT


async def test_explore_branches_have_distinct_payloads() -> None:
    """Diversification: each branch's params produce different mock outputs."""
    service, _ = _setup()
    results = await service.explore(task=_task())
    payloads = [r.payload for r in results]
    # The fold output paths embed the params, so they differ across branches.
    fold_paths = [p["fold"]["pdb_path"] for p in payloads]
    assert len(set(fold_paths)) == len(fold_paths)


async def test_explore_zero_fanout_raises() -> None:
    service, _ = _setup()
    with pytest.raises(BranchBudgetExceededError):
        await service.explore(task=_task(), fanout=0)


async def test_explore_max_total_branches_zero_raises() -> None:
    service, _ = _setup()
    with pytest.raises(BranchBudgetExceededError):
        await service.explore(task=_task(), max_total_branches=0)

"""Unit tests for agents/sub_agent.py — pipeline, skill selection, error path."""

from __future__ import annotations

import pytest

from proteinclaw.agents.branch_result import BranchStatus
from proteinclaw.agents.permissions import (
    PermissionDeniedError,
    ToolPermissionSet,
)
from proteinclaw.agents.sub_agent import (
    BranchParams,
    NoApplicableSkillError,
    SubAgent,
)
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


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(RCSB())
    reg.register(RFDiffusion3())
    reg.register(ProteinMPNN())
    reg.register(AlphaFold())
    reg.register(Foldseek())
    return reg


def _binder_skill() -> Skill:
    return Skill(
        id="binder_design",
        version=1,
        name="Binder",
        description="Binder design.",
        applicable_tasks=("binder_design",),
        body="Step 1: do thing.",
        provenance=SkillProvenance.HUMAN_AUTHORED,
    )


def _library() -> SkillLibrary:
    lib = SkillLibrary()
    lib.add(_binder_skill())
    return lib


def _task() -> Task:
    return Task(
        session_id="s1",
        description="Design a binder for 1ABC",
        inputs={"task_type": "binder_design", "target_pdb_id": "1ABC"},
    )


async def test_run_produces_completed_branch_with_expected_payload_keys() -> None:
    sub = SubAgent(
        registry=_registry(),
        skill_library=_library(),
        trace_store=InMemoryTraceStore(),
    )
    result = await sub.run(
        task=_task(),
        params=BranchParams(),
        permissions=ToolPermissionSet.parent(),
    )
    assert result.status is BranchStatus.COMPLETED
    assert result.skill_version_id == "binder_design@v1"
    assert {"rcsb", "rfdiffusion3", "protein_mpnn", "fold", "foldseek"} <= set(result.payload)


async def test_run_records_skill_selected_and_branch_completed_events() -> None:
    trace = InMemoryTraceStore()
    sub = SubAgent(registry=_registry(), skill_library=_library(), trace_store=trace)
    result = await sub.run(
        task=_task(), params=BranchParams(), permissions=ToolPermissionSet.parent()
    )
    events = await trace.read_session("s1")
    kinds = [e.kind.value for e in events]
    assert "skill.selected" in kinds
    assert "agent.branch_completed" in kinds
    # Each event for this branch carries the branch_id.
    branch_events = [e for e in events if e.branch_id == result.branch_id]
    assert branch_events


async def test_run_without_invoke_tools_permission_raises() -> None:
    sub = SubAgent(registry=_registry(), skill_library=_library(), trace_store=InMemoryTraceStore())
    locked = ToolPermissionSet(
        can_delegate=False,
        can_write_memory=False,
        can_ask_user=False,
        can_run_sandbox=False,
        can_invoke_tools=False,
    )
    with pytest.raises(PermissionDeniedError):
        await sub.run(task=_task(), params=BranchParams(), permissions=locked)


async def test_no_applicable_skill_raises() -> None:
    empty = SkillLibrary()
    sub = SubAgent(registry=_registry(), skill_library=empty, trace_store=InMemoryTraceStore())
    with pytest.raises(NoApplicableSkillError):
        await sub.run(task=_task(), params=BranchParams(), permissions=ToolPermissionSet.parent())


async def test_run_failed_tool_returns_failed_branch_with_backtrack_event() -> None:
    """Removing rfdiffusion3 from the registry triggers ToolExecutionError."""
    reg = _registry()
    # Drop rfdiffusion3; the registry will raise UnknownToolError, which
    # propagates as the underlying tool failure path. The sub-agent doesn't
    # currently translate UnknownToolError, so we trigger a failure differently:
    # invoke RFdiffusion3 with bad inputs by giving it a contradictory task.
    trace = InMemoryTraceStore()
    sub = SubAgent(registry=reg, skill_library=_library(), trace_store=trace)
    bad_task = Task(
        session_id="s1",
        description="Design a binder",
        inputs={"task_type": "binder_design", "contigs": ""},  # empty contig is fine
    )
    # Force a failure: pass num_designs over the bound by constructing a
    # branch with a value the schema rejects.
    forced = BranchParams(num_designs=999)  # exceeds rfdiffusion3 schema le=64
    result = await sub.run(task=bad_task, params=forced, permissions=ToolPermissionSet.parent())
    assert result.status is BranchStatus.FAILED
    events = await trace.read_session("s1")
    assert any(e.kind.value == "agent.branch_backtracked" for e in events)

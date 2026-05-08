"""SubAgent: runs a single branch.

Phase 4 ships a deterministic mock pipeline so the end-to-end orchestrator
test runs without an LLM. The pipeline is keyed on the bound skill — each
applicable skill drives the same generic `target → backbone → sequence →
fold → similarity` chain, parameterized by per-branch overrides so two
branches on the same task produce different outputs.

Phase 4+ swaps the hardcoded pipeline for an LLM-driven one that reads the
skill's Markdown body and selects tools dynamically. The interface
(`SubAgent.run(...) -> BranchResult`) stays the same.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from proteinclaw.agents.branch_result import BranchResult, BranchStatus
from proteinclaw.agents.permissions import ToolPermissionSet
from proteinclaw.common.logging import EventKind, TraceEvent, get_logger
from proteinclaw.memory.trace_store import TraceStore
from proteinclaw.orchestrator.task import Task
from proteinclaw.skills.skill import Skill
from proteinclaw.skills.skill_library import SkillLibrary
from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.registry import ToolRegistry, UnknownToolError

_log = get_logger(__name__)


class BranchParams(BaseModel):
    """Per-branch parameter overrides used to diversify exploration.

    The Branching Service generates a different `BranchParams` per branch
    so two siblings on the same task produce different outputs even with
    deterministic mock backends.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    num_designs: int = 4
    num_sequences: int = 4
    sampling_temperature: float = 0.1
    use_msa: bool = False


class NoApplicableSkillError(LookupError):
    """Raised when the SkillLibrary has no skill applicable to a task type."""


class SubAgent:
    """Runs one branch on one task.

    Construct once per process (cheap; stateless modulo the bound deps)
    and call `run()` per branch. The branch's `BranchResult` carries the
    `skill_version_id` it ran with — the raw material the Evolution
    Service consumes in Phase 7.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        skill_library: SkillLibrary,
        trace_store: TraceStore,
    ) -> None:
        """Bind the dependencies. Permissions arrive per call via `run()`."""
        self._registry = registry
        self._skills = skill_library
        self._trace = trace_store

    async def run(
        self,
        *,
        task: Task,
        params: BranchParams,
        permissions: ToolPermissionSet,
        parent_branch_id: str | None = None,
        depth: int = 0,
        skill: Skill | None = None,
    ) -> BranchResult:
        """Execute one branch and return its result.

        Args:
            task: The task this branch addresses.
            params: Per-branch parameter overrides.
            permissions: Capability set for this branch.
            parent_branch_id: Parent branch in the tree, or None for roots.
            depth: 0 for roots, 1 for children. Capped at 2 by the
                Branching Service.
            skill: Pre-selected skill. If None, the first applicable skill
                from the library is used.

        Returns:
            A `BranchResult` in COMPLETED, FAILED, or BACKTRACKED state.
        """
        permissions.require("can_invoke_tools")
        chosen = skill or self._pick_skill(task)
        running = BranchResult(
            session_id=task.session_id,
            task_id=task.task_id,
            parent_branch_id=parent_branch_id,
            depth=depth,
            skill_version_id=chosen.version_id,
        )
        await self._emit(
            running.branch_id,
            EventKind.SKILL_SELECTED,
            session_id=task.session_id,
            payload={"skill_version_id": chosen.version_id, "task_id": task.task_id},
        )

        try:
            payload = await self._run_pipeline(task, params, running.branch_id)
        except ToolExecutionError as e:
            failed = running.with_status(BranchStatus.FAILED, error=str(e))
            await self._emit(
                running.branch_id,
                EventKind.BRANCH_BACKTRACKED,
                session_id=task.session_id,
                payload={"reason": "tool_failed", "error": str(e)},
            )
            return failed

        completed = running.with_status(BranchStatus.COMPLETED, payload=payload)
        return completed

    def _pick_skill(self, task: Task) -> Skill:
        """Return the latest applicable skill for `task` (Phase 4: first match)."""
        task_type = str(task.inputs.get("task_type") or task.description)
        # The simplest possible match: scan applicable_tasks for any tag the
        # task description contains. This is intentionally cheap; Phase 4+
        # replaces it with an LLM-grounded ranker.
        text = task_type.lower()
        for skill in self._skills.all_latest():
            if any(tag.lower() in text for tag in skill.applicable_tasks):
                return skill
        raise NoApplicableSkillError(
            f"no skill applicable to task {task.task_id} (description: {task.description!r})"
        )

    async def _run_pipeline(
        self, task: Task, params: BranchParams, branch_id: str
    ) -> dict[str, Any]:
        """Execute a deterministic mock pipeline and pack outputs into a payload.

        The payload keys (`fold`, `foldseek`, etc.) match what
        `evaluation/metrics.py` extractors expect, so the Evaluator can
        score the branch directly.
        """
        target = str(task.inputs.get("target_pdb_id") or "1ABC")
        contigs = str(task.inputs.get("contigs") or "10-20/A1-50/30-40")
        payload: dict[str, Any] = {}

        # 1. Optional RCSB metadata fetch (skipped if RCSB tool isn't registered).
        try:
            rcsb_out = await self._registry.invoke("rcsb", {"pdb_id": target})
            payload["rcsb"] = rcsb_out.payload
        except UnknownToolError:
            pass

        # 2. Backbone generation.
        rfdiff = await self._registry.invoke(
            "rfdiffusion3",
            {
                "target_pdb_path": target,
                "contigs": contigs,
                "num_designs": params.num_designs,
            },
        )
        payload["rfdiffusion3"] = rfdiff.payload
        first_design = rfdiff.payload["designs"][0]

        # 3. Sequence design conditioned on the first backbone.
        mpnn = await self._registry.invoke(
            "protein_mpnn",
            {
                "backbone_pdb_path": first_design["pdb_path"],
                "num_sequences": params.num_sequences,
                "sampling_temperature": params.sampling_temperature,
            },
        )
        payload["protein_mpnn"] = mpnn.payload
        first_sequence = mpnn.payload["sequences"][0]["sequence"]

        # 4. Structure prediction on the first designed sequence.
        fold = await self._registry.invoke(
            "alphafold",
            {
                "sequence": first_sequence,
                "msa": "fake-msa" if params.use_msa else None,
            },
        )
        payload["fold"] = fold.payload  # extractors look here for plddt/ptm

        # 5. Novelty check via Foldseek.
        foldseek = await self._registry.invoke(
            "foldseek",
            {"query_pdb_path": fold.payload["pdb_path"], "max_hits": 5},
        )
        payload["foldseek"] = foldseek.payload

        await self._emit(
            branch_id,
            EventKind.BRANCH_COMPLETED,
            session_id=task.session_id,
            payload={"task_id": task.task_id, "tools_used": list(payload)},
        )
        return payload

    async def _emit(
        self,
        branch_id: str,
        kind: EventKind,
        *,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Append one trace event for this branch."""
        await self._trace.append(
            TraceEvent(
                session_id=session_id,
                component="agent.sub_agent",
                kind=kind,
                branch_id=branch_id,
                payload=payload,
            )
        )

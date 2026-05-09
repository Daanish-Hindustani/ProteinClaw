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

import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.agents.branch_result import BranchResult, BranchStatus
from proteinclaw.agents.budget import (
    MAX_DEPTH,
    BranchBudget,
    BranchBudgetExceededError,
)
from proteinclaw.agents.llm_executor import (
    DEFAULT_MAX_STEPS,
    DelegateRequest,
    LLMExecutor,
    SpawnChildFn,
    _Observation,
)
from proteinclaw.agents.permissions import ToolPermissionSet
from proteinclaw.common.llm import LLMClient, Message
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
        llm: LLMClient | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        """Bind the dependencies.

        Args:
            registry: Tool registry available to this branch.
            skill_library: Skill library for skill selection.
            trace_store: Where to emit trace events.
            llm: Optional LLM client. When set, the sub-agent executes
                tool calls dynamically through `LLMExecutor`. When None,
                falls back to the heuristic
                ``rcsb → rfdiffusion3 → protein_mpnn → alphafold → foldseek``
                pipeline — useful for tests and offline runs.
            max_steps: Cap on tool calls in the LLM-driven path.
        """
        self._registry = registry
        self._skills = skill_library
        self._trace = trace_store
        self._llm = llm
        self._max_steps = max_steps

    async def run(
        self,
        *,
        task: Task,
        params: BranchParams,
        permissions: ToolPermissionSet,
        parent_branch_id: str | None = None,
        depth: int = 0,
        skill: Skill | None = None,
        budget: BranchBudget | None = None,
    ) -> BranchResult:
        """Execute one branch and return its result.

        Args:
            task: The task this branch addresses.
            params: Per-branch parameter overrides.
            permissions: Capability set for this branch.
            parent_branch_id: Parent branch in the tree, or None for roots.
            depth: 0 for roots, 1 for children. Capped at 2 by the
                Branching Service.
            skill: Pre-selected skill. If None, the LLM (or heuristic
                fallback) picks one from the library.
            budget: Session-shared `BranchBudget`. When set and
                `permissions.can_delegate` is True, the LLM-driven
                executor may emit `delegate` actions to spawn children
                up to the budget. When None, delegation is denied at
                the executor and the LLM gets an error observation.

        Returns:
            A `BranchResult` in COMPLETED, FAILED, or BACKTRACKED state.
        """
        permissions.require("can_invoke_tools")
        chosen = skill or await self._pick_skill(task)
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
            parent_branch_id=parent_branch_id,
        )

        try:
            if self._llm is not None:
                payload = await self._run_llm_pipeline(
                    task=task,
                    skill=chosen,
                    branch_id=running.branch_id,
                    permissions=permissions,
                    depth=depth,
                    budget=budget,
                    parent_branch_id=parent_branch_id,
                )
            else:
                payload = await self._run_pipeline(task, params, running.branch_id)
        except ToolExecutionError as e:
            failed = running.with_status(BranchStatus.FAILED, error=str(e))
            await self._emit(
                running.branch_id,
                EventKind.BRANCH_BACKTRACKED,
                session_id=task.session_id,
                payload={"reason": "tool_failed", "error": str(e)},
                parent_branch_id=parent_branch_id,
            )
            return failed

        completed = running.with_status(BranchStatus.COMPLETED, payload=payload)
        return completed

    async def _pick_skill(self, task: Task) -> Skill:
        """Return the best skill for `task`.

        Selection is **LLM-driven over the entire skill library** — no
        keyword pre-filter (we used to filter by `applicable_tasks` tags,
        which let "hotspot residues" in a binder prompt steer to the
        wrong skill) and no keyword fallback. The LLM sees every skill
        and picks one. The skill's own `applicable_tasks` field stays in
        the catalog text so the model can use it as a hint, but it
        carries no code-side enforcement.

        Without an LLM bound (offline / test mode) we resolve via the
        structured ``task.inputs["task_type"]`` field, matching it
        directly against ``skill.id`` (an exact equality on an explicit
        input — not a keyword scan of the description). If task_type is
        unset we fall through to the single-candidate case.

        Raises:
            NoApplicableSkillError: When the library is empty, when the
                LLM picker fails to choose a valid id, or when there is
                no LLM bound, no task_type match, and the library is
                ambiguous.
        """
        candidates = self._skills.all_latest()
        if not candidates:
            raise NoApplicableSkillError(f"skill library is empty for task {task.task_id}")

        if self._llm is not None:
            # Unambiguous library: no need to spend an LLM call to pick
            # the only option. This is structural, not heuristic — there
            # is literally nothing else to choose.
            if len(candidates) == 1:
                return candidates[0]
            chosen_id = await _llm_pick_skill_id(
                llm=self._llm, task=task, candidates=candidates
            )
            if chosen_id is None:
                raise NoApplicableSkillError(
                    f"LLM skill picker did not return a valid skill for task {task.task_id}"
                )
            for s in candidates:
                if s.id == chosen_id:
                    return s
            raise NoApplicableSkillError(
                f"LLM picked unknown skill_id={chosen_id!r} for task {task.task_id}"
            )

        # Offline / no-LLM mode (tests, deterministic replays).
        # No keyword scanning of descriptions — only structured lookup.
        task_type = str(task.inputs.get("task_type") or "")
        if task_type:
            for s in candidates:
                if s.id == task_type:
                    return s
        if len(candidates) == 1:
            return candidates[0]
        raise NoApplicableSkillError(
            f"no LLM bound, no task_type match, and {len(candidates)} skills "
            f"available for task {task.task_id}; bind an LLM or set task_type."
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

    async def _run_llm_pipeline(
        self,
        *,
        task: Task,
        skill: Skill,
        branch_id: str,
        permissions: ToolPermissionSet,
        depth: int,
        budget: BranchBudget | None,
        parent_branch_id: str | None = None,
    ) -> dict[str, Any]:
        """Drive the LLM tool-calling loop and pack outputs into a payload.

        Mirrors the heuristic path's payload key conventions
        (``payload["fold"]`` for AlphaFold output) so the Evaluator's
        metric extractors keep working unchanged. Surfaces the task's
        success criteria to the LLM so it knows what to target, and —
        when permissions + budget allow — wires up a ``spawn_child``
        callback so the LLM can delegate sub-tasks.
        """
        assert self._llm is not None  # gated by caller
        executor = LLMExecutor(
            llm=self._llm,
            registry=self._registry,
            trace_store=self._trace,
            max_steps=self._max_steps,
        )

        spawn_child = self._build_spawn_child(
            parent_task=task,
            parent_branch_id=branch_id,
            depth=depth,
            permissions=permissions,
            budget=budget,
        )

        result = await executor.run(
            task_description=task.description,
            skill=skill,
            session_id=task.session_id,
            branch_id=branch_id,
            parent_branch_id=parent_branch_id,
            task_inputs=dict(task.inputs),
            success_criteria=task.success_criteria,
            spawn_child=spawn_child,
        )
        await self._emit(
            branch_id,
            EventKind.BRANCH_COMPLETED,
            session_id=task.session_id,
            payload={
                "task_id": task.task_id,
                "tools_used": [k for k in result.payload if k != "fold"],
                "steps_taken": result.steps_taken,
                "finished_explicitly": result.finished_explicitly,
                "summary": result.finish_summary,
            },
            parent_branch_id=parent_branch_id,
        )
        return result.payload

    def _build_spawn_child(
        self,
        *,
        parent_task: Task,
        parent_branch_id: str,
        depth: int,
        permissions: ToolPermissionSet,
        budget: BranchBudget | None,
    ) -> SpawnChildFn | None:
        """Build the spawn_child callback handed to the LLM executor.

        Returns None when delegation is forbidden — either by the
        permission set, by the depth cap, or by the absence of a budget.
        The executor turns a None spawner into a `delegate` observation
        with the reason; the LLM can then back off.

        The returned callable accepts the parent's running tool payload
        and observation history so the child sees its predecessor's
        outputs structurally, not via free-text instructions.
        """
        if not permissions.can_delegate:
            return None
        if depth >= MAX_DEPTH - 1:
            # depth=1 children would put the next level at depth=2 which
            # exceeds the cap. Disallow further delegation.
            return None
        if budget is None:
            return None

        async def spawn(
            request: DelegateRequest,
            *,
            parent_payload: dict[str, Any],
            parent_observations: Sequence[_Observation],
        ) -> dict[str, Any]:
            """Spawn one child sub-agent for `request` and return its payload."""
            try:
                budget.reserve()
            except BranchBudgetExceededError as e:
                # Surface to the executor as an observation, not a crash.
                raise BranchBudgetExceededError(str(e)) from None
            child_skill = self._pick_skill_for_child(request)
            # Inject parent context into the child's task_inputs under
            # well-known keys. The LLMExecutor renders these in the
            # child's system prompt under "## Parent context" so the
            # child reads paths/metrics directly from the parent's
            # actual outputs instead of guessing.
            parent_history = [
                _serialize_observation(o) for o in parent_observations
            ]
            child_inputs: dict[str, Any] = {
                **parent_task.inputs,
                **request.inputs,
                "_parent_payload": parent_payload,
                "_parent_history": parent_history,
            }
            child_task = parent_task.model_copy(
                update={
                    "task_id": str(uuid.uuid4()),
                    "description": request.description,
                    "inputs": child_inputs,
                }
            )
            child_result = await self.run(
                task=child_task,
                params=BranchParams(),
                permissions=ToolPermissionSet.child(),
                parent_branch_id=parent_branch_id,
                depth=depth + 1,
                skill=child_skill,
                budget=budget,
            )
            if child_result.status is not BranchStatus.COMPLETED:
                err_msg = child_result.error or "child branch did not complete"
                # Treated as a failed delegate from the executor's perspective.
                raise RuntimeError(err_msg)
            return dict(child_result.payload)

        return spawn

    def _pick_skill_for_child(self, request: DelegateRequest) -> Skill | None:
        """Resolve the child's skill from a `DelegateRequest`.

        - If the request names a skill_id and it exists, use it.
        - Otherwise return None and let the child's `_pick_skill` choose.
        """
        if not request.skill_id:
            return None
        try:
            return self._skills.latest(request.skill_id)
        except Exception:
            return None

    async def _emit(
        self,
        branch_id: str,
        kind: EventKind,
        *,
        session_id: str,
        payload: dict[str, Any],
        parent_branch_id: str | None = None,
    ) -> None:
        """Append one trace event for this branch.

        ``parent_branch_id`` defaults to None for root branches; pass
        the spawning branch's id for delegated children so the trace
        DB can reconstruct the tree.
        """
        await self._trace.append(
            TraceEvent(
                session_id=session_id,
                component="agent.sub_agent",
                kind=kind,
                branch_id=branch_id,
                parent_branch_id=parent_branch_id,
                payload=payload,
            )
        )


# ---------- LLM-driven skill picker ---------------------------------------


def _serialize_observation(obs: _Observation) -> dict[str, Any]:
    """Render one parent observation for inclusion in a child's task_inputs.

    Plain dicts (no dataclass) so the result is JSON-serializable for the
    Pydantic Task model.
    """
    return {
        "tool": obs.tool_name,
        "payload": obs.payload if obs.payload else None,
        "error": obs.error,
    }


class _SkillChoice(BaseModel):
    """LLM's chosen skill id, drawn from the candidate set."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(description="One of the offered candidate skill ids.")
    reasoning: str = ""


async def _llm_pick_skill_id(*, llm: LLMClient, task: Task, candidates: list[Skill]) -> str | None:
    """Ask the LLM to pick the best skill for `task`. None on parse failure."""
    catalog = "\n".join(f"- `{s.id}` ({s.name}): {s.description}" for s in candidates)
    user_msg = (
        f"## Task\n{task.description}\n\n"
        f"## Inputs\n{task.inputs}\n\n"
        f"## Candidate skills\n{catalog}\n\n"
        "Pick the single best `skill_id` from the candidates above."
    )
    try:
        choice = await llm.complete_structured(
            system=(
                "You select the best skill for a protein-design task from a "
                "small candidate list. Return only a `skill_id` from the list."
            ),
            messages=[Message(role="user", content=user_msg)],
            response_model=_SkillChoice,
        )
    except Exception as e:
        _log.info("sub_agent.llm_skill_pick_failed", error=str(e))
        return None
    valid_ids = {s.id for s in candidates}
    if choice.skill_id not in valid_ids:
        _log.info(
            "sub_agent.llm_skill_pick_invalid",
            chose=choice.skill_id,
            offered=sorted(valid_ids),
        )
        return None
    return choice.skill_id

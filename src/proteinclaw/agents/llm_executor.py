"""LLM-driven tool-calling loop used by `SubAgent` when an LLM is bound.

Each step:

1. The executor sends the LLM a system prompt describing the task, the
   bound skill's body, the tool catalog, and the history of `(action,
   result)` pairs so far.
2. The LLM emits a single `AgentAction` — either ``call_tool`` with a
   tool name + inputs, or ``finish`` with a summary.
3. The executor validates the action, calls the registry, and appends
   `(action, observation)` to the history.

Hard caps:

- ``max_steps`` calls per branch. Default 8. Hitting the cap is an
  ordinary termination (we keep whatever payload was built); it does
  not raise.
- A tool may be called at most twice. This kills loops where the LLM
  re-runs the same tool with the same inputs because it's confused.
- Tool errors abort the loop with a `ToolExecutionError` — the
  SubAgent layer catches it and marks the branch FAILED, exactly the
  same as the heuristic path.

Output payload key convention:

- Each tool's payload lands at ``payload[tool_name]``.
- The ``alphafold`` tool's output is *also* mirrored at
  ``payload["fold"]`` so the existing metric extractors
  (`extract_plddt`, `extract_ptm`) keep working unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.llm import LLMClient, Message
from proteinclaw.common.logging import EventKind, TraceEvent, get_logger
from proteinclaw.memory.trace_store import TraceStore
from proteinclaw.orchestrator.task import SuccessCriterion
from proteinclaw.skills.skill import Skill
from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.registry import ToolRegistry

DEFAULT_MAX_STEPS = 8
"""Cap on tool calls per branch — prevents runaway loops."""

DEFAULT_MAX_REPEATS_PER_TOOL = 2
"""Cap on calls to the same tool — prevents the LLM from spinning."""

_log = get_logger(__name__)


class DelegateRequest(BaseModel):
    """A request to spawn a child sub-agent for a sub-task.

    Attributes:
        description: Natural-language description of what the child
            should accomplish. Becomes the child Task's description.
        skill_id: Optional skill id to bind to the child. When None,
            the child picks its own skill via the same selection logic
            as the parent.
        inputs: Optional input overrides for the child Task.
    """

    model_config = ConfigDict(extra="forbid")

    description: str
    skill_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentAction(BaseModel):
    """One step the LLM-driven executor takes.

    Exactly one of these modes is active per step:

    - ``finish=True`` → branch complete; all other fields ignored.
    - ``tool_name`` set → call the registry tool with ``inputs``.
    - ``delegate`` set → spawn a child sub-agent with the given request.
    - none of the above → executor stops cleanly (LLM gave up).

    Schema kept flat (rather than a discriminated union) so the system
    prompt fits the schema-as-prose format that LiteLLM's structured
    output uses comfortably.

    Attributes:
        finish: Set True when the branch is done.
        tool_name: The tool to invoke.
        inputs: Arguments matching the tool's input schema.
        delegate: When set, spawn a child sub-agent for this sub-task.
            Children cannot themselves delegate (depth cap).
        reasoning: Free-form rationale; recorded in the trace.
        summary: Human-readable summary written when ``finish=True``.
    """

    model_config = ConfigDict(extra="forbid")

    finish: bool = False
    tool_name: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    delegate: DelegateRequest | None = None
    reasoning: str = ""
    summary: str = ""


@dataclass
class _Observation:
    """One tool result, recorded for the LLM's next turn."""

    tool_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ExecutorResult:
    """Aggregate output of one full executor run."""

    payload: dict[str, Any]
    steps_taken: int
    finish_summary: str = ""
    finished_explicitly: bool = False


_EXECUTOR_SYSTEM_PROMPT = """\
You are a sub-agent inside ProteinClaw running ONE branch of a protein-design task.

Your job is to call tools step by step, building a payload that the Evaluator
can score against the task's success criteria. Use the bound skill's workflow
as guidance. At each step emit a single JSON object describing the next
AgentAction.

Rules:

- The user-facing success criteria are listed under "## Success criteria"
  below. Plan your tool calls to produce values for each named metric.
- Set finish=true only when the payload covers every targeted metric
  (typically: an alphafold prediction supplying plddt + ptm; foldseek
  hits when novelty is targeted; precomputed RMSD/clash via the sandbox
  when those are targeted).
- Never invoke the same tool more than twice with the same inputs.
- When a tool fails, the failure is recorded as an observation. Try a
  different approach (different inputs, different tool, or finish=true if
  retrying is hopeless). Don't repeat the failing call.
- When you need ad-hoc analysis (RMSD computation, PDB parsing, metric
  extraction), call the `sandbox` tool with a Python snippet.
- When a sub-task is too large to fit in your remaining budget, emit a
  delegate action — a child sub-agent will handle it. Children cannot
  delegate further.
"""


class LLMExecutor:
    """Drives an LLMClient through a tool-calling loop for one branch."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        registry: ToolRegistry,
        trace_store: TraceStore,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_repeats_per_tool: int = DEFAULT_MAX_REPEATS_PER_TOOL,
    ) -> None:
        """Bind the LLM client + registry. Caps are conservative defaults."""
        self._llm = llm
        self._registry = registry
        self._trace = trace_store
        self._max_steps = max_steps
        self._max_repeats = max_repeats_per_tool

    async def run(
        self,
        *,
        task_description: str,
        skill: Skill,
        session_id: str,
        branch_id: str,
        task_inputs: dict[str, Any],
        success_criteria: tuple[SuccessCriterion, ...] = (),
        spawn_child: Callable[[DelegateRequest], Awaitable[dict[str, Any]]] | None = None,
    ) -> ExecutorResult:
        """Run the tool-calling loop until finish, cap, or unrecoverable failure.

        Args:
            task_description: Natural-language description.
            skill: Bound skill — its markdown body is shown to the LLM.
            session_id: For trace events.
            branch_id: For trace events.
            task_inputs: Free-form structured task inputs.
            success_criteria: Surfaced to the LLM so it knows what
                metrics the Evaluator will score. Empty tuple means the
                LLM relies solely on the skill body for guidance.
            spawn_child: Optional callable. When set, the LLM may emit
                ``delegate`` actions and the executor will await the
                child's payload before continuing. When None, delegate
                actions are recorded as errors.

        Returns:
            An `ExecutorResult` describing the run. Tool failures are
            recorded as observations and the loop continues — the
            caller's branch is only marked FAILED if the loop exhausts
            its budget without a recoverable next step.
        """
        catalog = _build_tool_catalog(self._registry)
        criteria_block = _format_criteria(success_criteria)
        observations: list[_Observation] = []
        payload: dict[str, Any] = {}
        call_counts: dict[str, int] = {}

        for step in range(1, self._max_steps + 1):
            action = await self._ask_next_action(
                task_description=task_description,
                task_inputs=task_inputs,
                skill_body=skill.body,
                catalog=catalog,
                observations=observations,
                criteria_block=criteria_block,
            )
            await self._emit(
                session_id=session_id,
                branch_id=branch_id,
                kind=EventKind.OPTIMIZER_STEP,
                payload={
                    "step": step,
                    "finish": action.finish,
                    "tool_name": action.tool_name,
                    "delegate": action.delegate is not None,
                    "reasoning": action.reasoning[:500],
                },
            )

            if action.finish:
                return ExecutorResult(
                    payload=payload,
                    steps_taken=step,
                    finish_summary=action.summary,
                    finished_explicitly=True,
                )

            if action.delegate is not None:
                child_payload = await self._handle_delegate(
                    request=action.delegate,
                    spawn_child=spawn_child,
                    observations=observations,
                )
                if child_payload is not None:
                    # Children land under a unique key so multiple delegates
                    # don't clobber each other.
                    key = f"child_{sum(1 for k in payload if k.startswith('child_')) + 1}"
                    payload[key] = child_payload
                continue

            if not action.tool_name:
                _log.warning("llm_executor.action_missing_tool", step=step)
                return ExecutorResult(
                    payload=payload,
                    steps_taken=step,
                    finish_summary="LLM emitted neither a tool nor finish; stopping.",
                )

            count_after = call_counts.get(action.tool_name, 0) + 1
            if count_after > self._max_repeats:
                _log.info(
                    "llm_executor.repeat_cap_hit",
                    tool=action.tool_name,
                    cap=self._max_repeats,
                )
                # Record as an observation so the LLM sees the cap hit and
                # picks a different tool next step — instead of immediately
                # stopping the branch.
                observations.append(
                    _Observation(
                        tool_name=action.tool_name,
                        error=f"repeat cap ({self._max_repeats}) reached for this tool",
                    )
                )
                continue
            call_counts[action.tool_name] = count_after

            try:
                output = await self._registry.invoke(action.tool_name, action.inputs)
            except ToolExecutionError as e:
                # Within-branch backtrack: surface the failure to the LLM
                # so it can choose a different tool / inputs / give up.
                # Do NOT bubble — that would mark the whole branch FAILED
                # before the LLM has a chance to react.
                _log.info(
                    "llm_executor.tool_failed",
                    tool=action.tool_name,
                    error=str(e),
                )
                await self._emit(
                    session_id=session_id,
                    branch_id=branch_id,
                    kind=EventKind.TOOL_FAILED,
                    payload={"tool": action.tool_name, "error": str(e)[:500]},
                )
                observations.append(_Observation(tool_name=action.tool_name, error=str(e)))
                continue

            payload[action.tool_name] = output.payload
            if action.tool_name == "alphafold":
                payload["fold"] = output.payload  # mirror so metric extractors find it
            observations.append(_Observation(tool_name=action.tool_name, payload=output.payload))

        return ExecutorResult(
            payload=payload,
            steps_taken=self._max_steps,
            finish_summary=f"hit max_steps={self._max_steps}",
        )

    async def _ask_next_action(
        self,
        *,
        task_description: str,
        task_inputs: dict[str, Any],
        skill_body: str,
        catalog: str,
        observations: Sequence[_Observation],
        criteria_block: str,
    ) -> AgentAction:
        """Produce one validated AgentAction from the LLM."""
        user_msg = (
            f"## Task\n{task_description}\n\n"
            f"## Task inputs\n{json.dumps(task_inputs, sort_keys=True)}\n\n"
            f"## Success criteria\n{criteria_block}\n\n"
            f"## Skill workflow (treat as guidance, not gospel)\n{skill_body}\n\n"
            f"## Tool catalog\n{catalog}\n\n"
            f"## Steps so far ({len(observations)})\n"
            f"{_format_observations(observations)}\n\n"
            "Emit the next AgentAction as JSON."
        )
        return await self._llm.complete_structured(
            system=_EXECUTOR_SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_msg)],
            response_model=AgentAction,
        )

    async def _handle_delegate(
        self,
        *,
        request: DelegateRequest,
        spawn_child: Callable[[DelegateRequest], Awaitable[dict[str, Any]]] | None,
        observations: list[_Observation],
    ) -> dict[str, Any] | None:
        """Spawn a child sub-agent for `request` if delegation is allowed.

        Returns the child's payload on success, None when delegation
        was rejected or failed. Failures are recorded as observations
        so the LLM can react.
        """
        if spawn_child is None:
            observations.append(
                _Observation(
                    tool_name="delegate",
                    error="delegation not permitted in this context",
                )
            )
            return None
        try:
            child_payload = await spawn_child(request)
        except Exception as e:  # delegation-level failures: budget, depth cap, etc.
            _log.info("llm_executor.delegate_failed", error=str(e))
            observations.append(_Observation(tool_name="delegate", error=str(e)))
            return None
        observations.append(
            _Observation(
                tool_name="delegate",
                payload={"description": request.description, "keys": list(child_payload)},
            )
        )
        return child_payload

    async def _emit(
        self,
        *,
        session_id: str,
        branch_id: str,
        kind: EventKind,
        payload: dict[str, Any],
    ) -> None:
        """Append a TraceEvent for one executor decision."""
        await self._trace.append(
            TraceEvent(
                session_id=session_id,
                component="agent.llm_executor",
                kind=kind,
                branch_id=branch_id,
                payload=payload,
            )
        )


def _build_tool_catalog(registry: ToolRegistry) -> str:
    """Render the registry as Markdown the LLM can read."""
    lines: list[str] = []
    for desc in registry.describe_all():
        lines.append(f"### `{desc.name}`")
        lines.append(desc.description)
        # Schemas are JSON-Schema dicts; trim to the property list to keep prompts short.
        properties = desc.input_schema.get("properties", {})
        if properties:
            lines.append("Inputs:")
            for field_name, field_schema in properties.items():
                ftype = field_schema.get("type", "?")
                desc_text = field_schema.get("description", "")
                lines.append(f"  - `{field_name}` ({ftype}): {desc_text}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_criteria(criteria: Sequence[SuccessCriterion]) -> str:
    """Render the task's success criteria as a Markdown list for the LLM."""
    if not criteria:
        return "(no explicit criteria — finish when the skill workflow's outputs are present)"
    lines: list[str] = []
    for c in criteria:
        comp = {"gte": "≥", "lte": "≤", "eq": "="}.get(c.comparison.value, c.comparison.value)
        line = f"- **{c.name}** — {c.metric.value} {comp} {c.threshold}"
        if c.description:
            line += f" ({c.description})"
        lines.append(line)
    return "\n".join(lines)


def _format_observations(observations: Sequence[_Observation]) -> str:
    """Render observation history compactly. Truncates long payloads."""
    if not observations:
        return "(none yet)"
    out: list[str] = []
    for i, obs in enumerate(observations, start=1):
        if obs.error:
            out.append(f"{i}. {obs.tool_name} → ERROR: {obs.error[:200]}")
            continue
        # Only show top-level keys + a short preview of each value to keep
        # prompts under control on long tool outputs.
        keys = list(obs.payload)
        preview = ", ".join(f"{k}={_summarize(obs.payload[k])}" for k in keys[:6])
        out.append(f"{i}. {obs.tool_name} → {preview}")
    return "\n".join(out)


def _summarize(value: Any) -> str:
    """One-line summary of a payload value — truncated if long."""
    if isinstance(value, str):
        return value if len(value) <= 80 else value[:77] + "..."
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)

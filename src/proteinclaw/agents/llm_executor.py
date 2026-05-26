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
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from proteinclaw.common.litellm_client import LLMResponseError
from proteinclaw.common.llm import LLMClient, Message
from proteinclaw.common.logging import EventKind, TraceEvent, get_logger
from proteinclaw.memory.trace_store import TraceStore
from proteinclaw.orchestrator.task import SuccessCriterion
from proteinclaw.skills.skill import Skill
from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.registry import ToolRegistry

class SpawnChildFn(Protocol):
    """Callback the LLM executor uses to spawn delegated children.

    Implemented by ``SubAgent._build_spawn_child``. The protocol form
    captures the full set of context the child must receive: the
    delegation request, the parent's accumulated tool payload (so the
    child can read paths/metrics directly), and the parent's full
    observation history (so the child can replay the parent's reasoning
    if it needs to). Anything less and the child has to re-run upstream
    tools — wasteful and a frequent source of hallucinated paths.
    """

    async def __call__(
        self,
        request: DelegateRequest,
        *,
        parent_payload: dict[str, Any],
        parent_observations: Sequence["_Observation"],
    ) -> dict[str, Any]:
        """Spawn one child sub-agent and return its payload."""
        ...


DEFAULT_MAX_STEPS = 24
"""Cap on tool calls per branch — prevents runaway loops.

Sized to fit the full binder workflow with realistic LLM scratch
analysis. Floor: rcsb + rfdiffusion3 + (per-design) protein_mpnn +
(per-seq) alphafold + foldseek = ≥5 tool calls; the extra budget covers
sandbox snippets the LLM uses for analysis, plus one or two retries
when an input was malformed. If you raise this further, also raise the
session-wide branch budget so a single deep branch can't starve its
siblings.
"""

DEFAULT_MAX_REPEATS_PER_TOOL = 2
"""Cap on calls to the same tool — prevents the LLM from spinning."""

_log = get_logger(__name__)

_REASONING_LOG_LIMIT = 600
"""Max reasoning chars surfaced to the CLI/log. Full text is in the trace."""


def _truncate_for_log(text: str) -> str:
    """Collapse newlines and clip ``text`` to fit on one log line."""
    if not text:
        return ""
    flat = " ".join(text.split())
    if len(flat) <= _REASONING_LOG_LIMIT:
        return flat
    return flat[:_REASONING_LOG_LIMIT] + "…"


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

    # ``extra="ignore"`` rather than ``"forbid"``: in practice the LLM
    # routinely emits an extra ``payload`` / ``results`` field summarizing
    # what it intends to return. Forbidding those caused the entire
    # AgentAction parse to fail, the executor to bubble the error, and
    # the orchestrator to crash mid-run. Ignoring extras keeps the
    # canonical control fields strict while letting the LLM be sloppier.
    model_config = ConfigDict(extra="ignore")

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
- Prefer real tools over `sandbox`. Use `sandbox` only for analysis the
  tools don't already produce (custom metrics, ad-hoc PDB parsing).
  Don't waste step budget formatting strings or recomputing values that
  are already in a tool's output payload.

## Parent context (for delegated children only)

If the user message contains a "## Parent context" section, you are a
CHILD sub-agent. Your parent has already executed some tools — those
outputs are listed there with concrete paths and values. Read them
first. Pass the parent's actual paths (e.g. ``pdb_path`` from a
backbone the parent already generated) directly into your own tool
calls; never re-run a tool the parent has already run unless its
output is missing or unusable. If the section is absent you are a
root branch — start from scratch using the skill workflow below.

## Delegation

You have a `delegate` action that spawns a CHILD sub-agent for one
focused sub-task. Children run in their own branch with their own step
budget — use them whenever a task is naturally a fan-out and would
otherwise consume your steps serially. Children cannot themselves
delegate (depth cap = 2).

Delegate when ANY of these is true:

- You need to fold N candidate sequences and rank them — emit one
  `delegate` per sequence (or one delegate that handles the per-seq
  batch using the alphafold tool). Don't fold them all yourself.
- You need to design sequences for several backbones independently —
  one delegate per backbone, each running ProteinMPNN + AlphaFold for
  its own input.
- A side-quest is needed (e.g. picking hotspots on a target structure
  before binder design proper) that has its own skill in the library.
  Delegate it with `skill_id` set to that skill.
- Your remaining step budget is too small to cover the rest of the
  workflow. Hand off the residual task to a child rather than running
  out of steps mid-pipeline.

Each delegate's payload is merged into your payload under a
`child_<n>` key — read those when ranking final candidates.
"""


_EXECUTOR_SYSTEM_PROMPT = _EXECUTOR_SYSTEM_PROMPT.rstrip() + """

If the task prompt says delegation is disabled, or if an observation says
"delegation not permitted", do not try `delegate` again. Continue with direct
tool calls and finish with the best payload you can produce.
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
        spawn_child: SpawnChildFn | None = None,
        parent_branch_id: str | None = None,
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
            try:
                action = await self._ask_next_action(
                    task_description=task_description,
                    task_inputs=task_inputs,
                    skill_body=skill.body,
                    catalog=catalog,
                    observations=observations,
                    criteria_block=criteria_block,
                    delegation_block=_format_delegation_availability(spawn_child),
                )
            except LLMResponseError as e:
                # Pydantic validation / JSON parse failure — record as an
                # observation so the LLM sees its own malformed reply and
                # gets a chance to correct it on the next step. Without
                # this catch, a single bad response crashed the entire
                # orchestrator (this fired in run #6 when the LLM
                # repeatedly added a ``payload`` field to AgentAction).
                _log.info("llm_executor.action_parse_failed", error=str(e))
                observations.append(
                    _Observation(
                        tool_name="llm",
                        error=f"your last reply could not be parsed as AgentAction: {e}",
                    )
                )
                continue
            await self._emit(
                session_id=session_id,
                branch_id=branch_id,
                kind=EventKind.OPTIMIZER_STEP,
                payload={
                    "step": step,
                    "finish": action.finish,
                    "tool_name": action.tool_name,
                    "delegate": action.delegate is not None,
                    "reasoning": action.reasoning[:1000],
                },
                parent_branch_id=parent_branch_id,
            )
            # Surface the agent's intent live in the CLI. Operators get
            # to see which tool the LLM chose AND its rationale at every
            # step, instead of staring at silent backoffs and only learning
            # what happened from the trace DB after the fact.
            _action_label = (
                "finish"
                if action.finish
                else f"delegate→{action.delegate.skill_id or '?'}"
                if action.delegate is not None
                else (action.tool_name or "noop")
            )
            _log.info(
                "agent.step",
                branch=branch_id[:8],
                step=step,
                action=_action_label,
                reasoning=_truncate_for_log(action.reasoning),
            )

            if action.finish:
                return ExecutorResult(
                    payload=payload,
                    steps_taken=step,
                    finish_summary=action.summary,
                    finished_explicitly=True,
                )

            if action.delegate is not None:
                if spawn_child is None and _has_delegation_not_permitted(observations):
                    _log.info("llm_executor.repeated_disabled_delegate", branch=branch_id[:8])
                    observations.append(
                        _Observation(
                            tool_name="delegate",
                            error="repeated invalid delegate action; stopping this branch",
                        )
                    )
                    return ExecutorResult(
                        payload=payload,
                        steps_taken=step,
                        finish_summary=(
                            "stopped after repeated delegate action in a context "
                            "where delegation is disabled"
                        ),
                    )
                child_payload = await self._handle_delegate(
                    request=action.delegate,
                    spawn_child=spawn_child,
                    observations=observations,
                    parent_payload=payload,
                    parent_observations=observations,
                )
                if child_payload is not None:
                    # Children land under a unique key so multiple delegates
                    # don't clobber each other.
                    key = f"child_{sum(1 for k in payload if k.startswith('child_')) + 1}"
                    payload[key] = child_payload
                    _promote_best_child_outputs(payload)
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
                    payload={"tool": action.tool_name, "error": str(e)[:4000]},
                    parent_branch_id=parent_branch_id,
                )
                observations.append(_Observation(tool_name=action.tool_name, error=str(e)))
                continue

            payload[action.tool_name] = output.payload
            if action.tool_name == "alphafold":
                payload["fold"] = output.payload  # mirror so metric extractors find it
            observations.append(_Observation(tool_name=action.tool_name, payload=output.payload))
            _log.info(
                "agent.tool_ok",
                branch=branch_id[:8],
                step=step,
                tool=action.tool_name,
                keys=list(output.payload)[:6],
            )

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
        delegation_block: str,
    ) -> AgentAction:
        """Produce one validated AgentAction from the LLM."""
        # Pull parent-delegation context out of task_inputs so it gets a
        # dedicated, prominently labelled section instead of being buried
        # in raw JSON. The keys are conventions set by SubAgent.spawn().
        bare_inputs = {
            k: v
            for k, v in task_inputs.items()
            if k not in {"_parent_payload", "_parent_history"}
        }
        parent_block = _format_parent_context(
            payload=task_inputs.get("_parent_payload"),
            history=task_inputs.get("_parent_history"),
        )
        sections = [
            f"## Task\n{task_description}",
            f"## Task inputs\n{json.dumps(bare_inputs, sort_keys=True)}",
        ]
        if parent_block:
            sections.append(parent_block)
        sections.extend(
            [
                f"## Success criteria\n{criteria_block}",
                f"## Delegation availability\n{delegation_block}",
                f"## Skill workflow (treat as guidance, not gospel)\n{skill_body}",
                f"## Tool catalog\n{catalog}",
                f"## Steps so far ({len(observations)})\n"
                f"{_format_observations(observations)}",
                "Emit the next AgentAction as JSON.",
            ]
        )
        user_msg = "\n\n".join(sections)
        return await self._llm.complete_structured(
            system=_EXECUTOR_SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_msg)],
            response_model=AgentAction,
        )

    async def _handle_delegate(
        self,
        *,
        request: DelegateRequest,
        spawn_child: SpawnChildFn | None,
        observations: list[_Observation],
        parent_payload: dict[str, Any],
        parent_observations: list[_Observation],
    ) -> dict[str, Any] | None:
        """Spawn a child sub-agent for `request` if delegation is allowed.

        ``parent_payload`` carries every tool output the parent has
        produced so far; ``parent_observations`` carries the parent's
        full step-by-step history. Both are forwarded to the spawner so
        the child sees its predecessor's work directly instead of having
        to re-derive paths and metrics from a free-text instruction.

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
            child_payload = await spawn_child(
                request,
                parent_payload=parent_payload,
                parent_observations=parent_observations,
            )
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
        parent_branch_id: str | None = None,
    ) -> None:
        """Append a TraceEvent for one executor decision."""
        await self._trace.append(
            TraceEvent(
                session_id=session_id,
                component="agent.llm_executor",
                kind=kind,
                branch_id=branch_id,
                parent_branch_id=parent_branch_id,
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


def _format_delegation_availability(spawn_child: SpawnChildFn | None) -> str:
    """Tell the LLM whether delegate actions are currently available."""
    if spawn_child is None:
        return (
            "DISABLED. You are not allowed to delegate from this branch. "
            "Do not emit a delegate action; call tools directly or finish."
        )
    return "ENABLED. You may delegate independent sub-tasks when useful."


def _has_delegation_not_permitted(observations: Sequence[_Observation]) -> bool:
    """Return True after the LLM already tried to delegate from a child branch."""
    return any(
        obs.tool_name == "delegate"
        and obs.error is not None
        and "delegation not permitted" in obs.error
        for obs in observations
    )


def _format_parent_context(
    *,
    payload: Any,
    history: Any,
) -> str:
    """Render the parent's payload + observation history for a child agent.

    Returns ``""`` when both inputs are missing — the calling code skips
    the section in that case so root branches don't see an empty
    "## Parent context" header.
    """
    if not payload and not history:
        return ""
    lines = ["## Parent context"]
    lines.append(
        "You are a delegated child sub-agent. Read this section first — "
        "the data below is what your parent has ALREADY produced. "
        "Use these paths/values directly; do NOT re-run upstream tools."
    )
    if payload:
        lines.append("### Parent payload (every tool the parent has called)")
        for tool_name in sorted(payload.keys() if isinstance(payload, dict) else []):
            lines.append(f"- `{tool_name}` → {_summarize(payload[tool_name])}")
    if history:
        lines.append("### Parent history (in order)")
        if isinstance(history, list):
            for i, step in enumerate(history, start=1):
                if not isinstance(step, dict):
                    continue
                tool = step.get("tool", "?")
                if step.get("error"):
                    lines.append(f"{i}. {tool} → ERROR: {str(step['error'])[:300]}")
                else:
                    pl = step.get("payload") or {}
                    lines.append(f"{i}. {tool} → {_summarize(pl)}")
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


_FULL_EXPAND_BUDGET = 1500
"""Char budget for fully-expanded list/dict rendering.

When the entire structure fits inside this budget, we render every
item — sequences, designs, foldseek hits — so the LLM can address them
by index without needing sandbox round-trips to re-read FASTA files.
This is the single biggest win against "spinning trying to find seq 2".
"""


def _summarize(value: Any) -> str:
    """One-line summary of a payload value — truncated if long.

    Strategy:

    - Strings: clip to 120 chars (paths and 80-residue sequences fit).
    - Lists/tuples: if the *fully expanded* form fits in
      ``_FULL_EXPAND_BUDGET``, emit every item so the LLM sees all of
      them. Otherwise show the first and a "+N more" tag.
    - Dicts: same — full expansion if it fits, otherwise priority-key
      preview.

    The full-expand path matters most for ``protein_mpnn`` outputs:
    4 sequences × ~80 chars + scores ≈ 600 chars, well within budget.
    Before this change the summary read ``sequences=[…, +3 more]`` and
    the LLM wasted half its budget trying to read FASTA files via
    sandbox to recover the truncated entries.
    """
    if isinstance(value, str):
        return value if len(value) <= 120 else value[:117] + "..."
    if isinstance(value, (list, tuple)):
        n = len(value)
        if n == 0:
            return "[]"
        full = "[" + ", ".join(_summarize(v) for v in value) + "]"
        if len(full) <= _FULL_EXPAND_BUDGET:
            return full
        first = _summarize(value[0])
        return f"[{first}, +{n - 1} more]"
    if isinstance(value, dict):
        items = list(value.items())
        if not items:
            return "{}"
        full = "{" + ", ".join(f"{k}={_summarize(v)}" for k, v in items) + "}"
        if len(full) <= _FULL_EXPAND_BUDGET:
            return full
        priority_keys = (
            "pdb_path",
            "design_id",
            "sequence",
            "score",
            "plddt",
            "ptm",
            "tm_score",
            "target",
            "id",
            "path",
        )
        preview_keys = [k for k in priority_keys if k in value][:4]
        if not preview_keys:
            preview_keys = list(value)[:4]
        inner = ", ".join(f"{k}={_summarize(value[k])}" for k in preview_keys)
        rest = len(items) - len(preview_keys)
        suffix = f", +{rest} more keys" if rest > 0 else ""
        return "{" + inner + suffix + "}"
    return str(value)


def _promote_best_child_outputs(payload: dict[str, Any]) -> None:
    """Mirror the best delegated child outputs into canonical payload keys.

    The evaluator scores branch-level keys like ``payload["fold"]``. When a
    parent delegates ProteinMPNN/AlphaFold work, the useful metrics can be
    buried under ``child_N`` and would otherwise look absent. Promote the
    child with the strongest fold confidence so delegated scientific work is
    visible to the same metric extractors as direct tool calls.
    """
    best = _best_scored_payload(payload)
    if best is None:
        return
    for key in ("fold", "alphafold", "protein_mpnn", "foldseek"):
        if key in best:
            payload[key] = best[key]


def _best_scored_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the nested payload with the best fold score, if any."""
    best_payload: dict[str, Any] | None = None
    best_score = -1.0
    for candidate in _iter_payloads(payload):
        fold = candidate.get("fold") or candidate.get("alphafold")
        if not isinstance(fold, dict):
            continue
        score = _fold_score(fold)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best_payload = candidate
    return best_payload


def _iter_payloads(payload: dict[str, Any]) -> Sequence[dict[str, Any]]:
    """Yield ``payload`` and all nested child payload dicts."""
    out: list[dict[str, Any]] = [payload]
    for key, value in payload.items():
        if key.startswith("child_") and isinstance(value, dict):
            out.extend(_iter_payloads(value))
    return out


def _fold_score(fold: dict[str, Any]) -> float | None:
    """Score a fold by pLDDT first, then pTM as a tie-breaker."""
    plddt = fold.get("plddt")
    ptm = fold.get("ptm")
    if not isinstance(plddt, (int, float)) and not isinstance(ptm, (int, float)):
        return None
    plddt_f = float(plddt) if isinstance(plddt, (int, float)) else 0.0
    ptm_f = float(ptm) if isinstance(ptm, (int, float)) else 0.0
    return plddt_f + 0.01 * ptm_f

# Trace Format

Every event in the run trace is an immutable `TraceEvent` defined in
`src/proteinclaw/common/logging.py`. Replaying events from the Trace Store
in insertion order MUST be sufficient to reconstruct the session — this
is a correctness requirement, not a nice-to-have.

## TraceEvent shape

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | UUIDv4, auto-generated. |
| `timestamp` | `datetime` | UTC-aware, auto-generated. |
| `session_id` | `str` | Owning session. |
| `component` | `str` | Originating component (e.g. `"orchestrator"`, `"tool.rfdiffusion3"`). |
| `kind` | `EventKind` | One of the enum values below — never inline strings. |
| `branch_id` | `str \| None` | Branch this event belongs to. |
| `parent_branch_id` | `str \| None` | Parent in the branch tree. |
| `payload` | `dict[str, Any]` | Free-form structured data. JSON-serializable. |

The model is `frozen=True, extra="forbid"` — events cannot be mutated
after construction and unknown fields raise `ValidationError`.

## Canonical event kinds

<!-- AUTO-GENERATED:event-kinds (source: src/proteinclaw/common/logging.py::EventKind) -->

| `EventKind` member | Wire value | Component |
|---|---|---|
| `SESSION_STARTED` | `session.started` | Lifecycle |
| `SESSION_ENDED` | `session.ended` | Lifecycle |
| `REQUEST_RECEIVED` | `orchestrator.request_received` | Orchestrator |
| `PLAN_PRODUCED` | `orchestrator.plan_produced` | Orchestrator |
| `ITERATION_STARTED` | `orchestrator.iteration_started` | Orchestrator |
| `ITERATION_FINISHED` | `orchestrator.iteration_finished` | Orchestrator |
| `BRANCH_SPAWNED` | `agent.branch_spawned` | Branching / sub-agents |
| `BRANCH_COMPLETED` | `agent.branch_completed` | Branching / sub-agents |
| `BRANCH_BACKTRACKED` | `agent.branch_backtracked` | Branching / sub-agents |
| `TOOL_INVOKED` | `tool.invoked` | Tools |
| `TOOL_SUCCEEDED` | `tool.succeeded` | Tools |
| `TOOL_FAILED` | `tool.failed` | Tools |
| `SKILL_SELECTED` | `skill.selected` | Skills |
| `SKILL_PATCHED` | `skill.patched` | Skills |
| `SKILL_REJECTED` | `skill.rejected` | Skills |
| `EVALUATION_PRODUCED` | `evaluator.produced` | Evaluator |
| `OPTIMIZER_STEP` | `evolution.optimizer_step` | Evolution |
| `OPTIMIZER_ACCEPTED` | `evolution.candidate_accepted` | Evolution |

<!-- /AUTO-GENERATED:event-kinds -->

## Compaction

Long traces are collapsed into a structured summary by
`src/proteinclaw/memory/compaction.py`. The compactor preserves a fixed
set of *audit-critical* event kinds verbatim and replaces the rest with
a `Goal | Progress | Decisions | Files | Next Steps` template. The
preserved set is `PRESERVED_KINDS` in that module:

- `SESSION_STARTED`, `SESSION_ENDED`
- `PLAN_PRODUCED`
- `TOOL_FAILED`, `BRANCH_BACKTRACKED`, `SKILL_REJECTED`
- `EVALUATION_PRODUCED`
- `OPTIMIZER_ACCEPTED`

Adding new event kinds: extend `EventKind` *and* decide whether the new
kind belongs in `PRESERVED_KINDS`. If it carries irreversible decision
information (a verdict, a rejection, a fail), preserve it.

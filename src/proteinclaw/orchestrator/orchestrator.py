"""Orchestrator: drives the 8-stage workflow end-to-end.

Phase 4 implements:

1. Intake: capture the user request, open a Session.
2. Plan: ask the Planner for a tuple of Tasks.
3. For each Task, iterate up to `MAX_ITERATIONS = 3`:
   a. BranchingService.explore → tuple[BranchResult, ...]
   b. Evaluator.evaluate per non-failed branch.
   c. If any branch produces STOP_SUCCESS → bind that branch as the winner
      and break out of the loop.
   d. Otherwise → continue (RETRY/BRANCH all become "iterate again" at
      Phase 4 — the params don't differ across iterations yet, but the
      hook is there for Phase 4+).
4. Finalize: assemble final payload, emit SESSION_ENDED, persist.

Every step writes to the Trace Store. Replaying events from the store in
insertion order reconstructs the run — required by the quality bar in
CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

from proteinclaw.agents.branch_result import BranchResult, BranchStatus
from proteinclaw.agents.branching_service import BranchingService
from proteinclaw.common.logging import EventKind, TraceEvent, get_logger
from proteinclaw.evaluation.evaluator import Evaluator
from proteinclaw.evaluation.scoring import Evaluation, Verdict
from proteinclaw.memory.session_store import Session, SessionStore
from proteinclaw.memory.trace_store import TraceStore
from proteinclaw.orchestrator.planner import Planner
from proteinclaw.orchestrator.task import Task, TaskStatus

MAX_ITERATIONS = 1
"""Hard cap on orchestrator iterations per task.

Lowered from 3 to 1 to control wall clock during development. Iteration
2/3 historically just retried the same workflow with the same prompt
and the same skill, almost never producing a different verdict. Re-raise
when the Evolution Service starts mutating skills between iterations."""

_log = get_logger(__name__)


class _TaskOutcome:
    """Holder for the per-task winner and final evaluation."""

    def __init__(
        self,
        *,
        task: Task,
        winner: BranchResult | None,
        evaluation: Evaluation | None,
        iterations_used: int,
    ) -> None:
        """Construct an outcome record."""
        self.task = task
        self.winner = winner
        self.evaluation = evaluation
        self.iterations_used = iterations_used


class Orchestrator:
    """Top-level driver. Construct once per session-creating process."""

    def __init__(
        self,
        *,
        planner: Planner,
        branching_service: BranchingService,
        evaluator: Evaluator,
        session_store: SessionStore,
        trace_store: TraceStore,
    ) -> None:
        """Bind the components. All deps are required."""
        self._planner = planner
        self._branching = branching_service
        self._evaluator = evaluator
        self._sessions = session_store
        self._trace = trace_store

    async def run(
        self,
        user_request: str,
        *,
        fanout: int | None = None,
        iterations: int | None = None,
    ) -> Session:
        """Drive one user request through the full workflow.

        Args:
            user_request: Natural-language request.
            fanout: Optional override for ``MAX_FANOUT``. Clamped to the
                value of the constant (the cap can only be lowered, not
                raised, at runtime — change the constant if you need more).
            iterations: Optional override for ``MAX_ITERATIONS`` with the
                same clamping rule.

        Returns:
            The finalized `Session` with `final_payload` and `ended_at` set.
        """
        session = Session(user_request=user_request)
        await self._sessions.save(session)
        await self._emit(
            EventKind.SESSION_STARTED,
            session_id=session.session_id,
            component="orchestrator",
            payload={"user_request": user_request},
        )
        await self._emit(
            EventKind.REQUEST_RECEIVED,
            session_id=session.session_id,
            component="orchestrator",
            payload={"user_request": user_request},
        )

        tasks = await self._planner.plan(user_request=user_request, session_id=session.session_id)
        for t in tasks:
            session = session.with_task(t.task_id)
        await self._sessions.save(session)
        await self._emit(
            EventKind.PLAN_PRODUCED,
            session_id=session.session_id,
            component="orchestrator",
            payload={"task_count": len(tasks), "task_ids": [t.task_id for t in tasks]},
        )

        outcomes: list[_TaskOutcome] = []
        for task in tasks:
            outcome = await self._run_task(
                task=task,
                session=session,
                fanout=fanout,
                iterations=iterations,
            )
            outcomes.append(outcome)
            session = session.model_copy(
                update={"iterations_used": session.iterations_used + outcome.iterations_used}
            )
            await self._sessions.save(session)

        final_payload = _build_final_payload(outcomes)
        session = session.finalized(final_payload)
        await self._sessions.save(session)
        await self._emit(
            EventKind.SESSION_ENDED,
            session_id=session.session_id,
            component="orchestrator",
            payload={
                "task_count": len(outcomes),
                "winners": [o.winner.branch_id for o in outcomes if o.winner is not None],
            },
        )
        return session

    async def _run_task(
        self,
        *,
        task: Task,
        session: Session,
        fanout: int | None = None,
        iterations: int | None = None,
    ) -> _TaskOutcome:
        """Iterate the branch-evaluate loop on `task` until success or the cap."""
        winner: BranchResult | None = None
        last_eval: Evaluation | None = None
        iterations_used = 0

        max_iters = min(task.max_iterations, MAX_ITERATIONS)
        if iterations is not None:
            max_iters = max(1, min(max_iters, iterations))
        for iteration in range(max_iters):
            iterations_used = iteration + 1
            await self._emit(
                EventKind.ITERATION_STARTED,
                session_id=session.session_id,
                component="orchestrator",
                payload={"task_id": task.task_id, "iteration": iteration + 1},
            )

            explore_kwargs: dict[str, int] = {}
            if fanout is not None:
                explore_kwargs["fanout"] = max(1, fanout)
            branches = await self._branching.explore(task=task, **explore_kwargs)
            evaluations = await self._evaluate_branches(task=task, branches=branches)
            stopper = _pick_winner(evaluations)
            if stopper is not None:
                winner_branch = next(b for b in branches if b.branch_id == stopper.branch_id)
                winner = winner_branch
                last_eval = stopper
                await self._emit(
                    EventKind.ITERATION_FINISHED,
                    session_id=session.session_id,
                    component="orchestrator",
                    payload={
                        "task_id": task.task_id,
                        "iteration": iteration + 1,
                        "verdict": stopper.verdict.value,
                        "winner_branch_id": winner.branch_id,
                    },
                )
                break

            # No winner this iteration: keep the strongest evaluation as the
            # working candidate; if the cap is hit, this becomes the result.
            if evaluations:
                last_eval = max(
                    evaluations,
                    key=lambda e: sum(1 for s in e.score.metric_scores if s.passed),
                )
                winner = next(
                    (b for b in branches if b.branch_id == last_eval.branch_id),
                    None,
                )
            await self._emit(
                EventKind.ITERATION_FINISHED,
                session_id=session.session_id,
                component="orchestrator",
                payload={
                    "task_id": task.task_id,
                    "iteration": iteration + 1,
                    "verdict": last_eval.verdict.value if last_eval else "no_branches",
                    "winner_branch_id": winner.branch_id if winner else None,
                },
            )

        final_status = (
            TaskStatus.COMPLETED
            if (last_eval is not None and last_eval.verdict is Verdict.STOP_SUCCESS)
            else TaskStatus.FAILED
        )
        del final_status  # status would be persisted alongside the Task in Phase 5
        return _TaskOutcome(
            task=task,
            winner=winner,
            evaluation=last_eval,
            iterations_used=iterations_used,
        )

    async def _evaluate_branches(
        self, *, task: Task, branches: tuple[BranchResult, ...]
    ) -> list[Evaluation]:
        """Run the evaluator on every COMPLETED branch and emit trace events."""
        out: list[Evaluation] = []
        for b in branches:
            if b.status is not BranchStatus.COMPLETED:
                continue
            ev = self._evaluator.evaluate(
                branch_id=b.branch_id,
                task_id=b.task_id,
                criteria=task.success_criteria,
                payload=b.payload,
            )
            out.append(ev)
            await self._emit(
                EventKind.EVALUATION_PRODUCED,
                session_id=task.session_id,
                component="evaluator",
                branch_id=b.branch_id,
                payload={
                    "task_id": task.task_id,
                    "verdict": ev.verdict.value,
                    "passed": [s.metric.value for s in ev.score.metric_scores if s.passed],
                    "failed": [s.metric.value for s in ev.score.metric_scores if s.passed is False],
                },
            )
        return out

    async def _emit(
        self,
        kind: EventKind,
        *,
        session_id: str,
        component: str,
        payload: dict[str, Any],
        branch_id: str | None = None,
    ) -> None:
        """Append one trace event."""
        await self._trace.append(
            TraceEvent(
                session_id=session_id,
                component=component,
                kind=kind,
                branch_id=branch_id,
                payload=payload,
            )
        )


def _pick_winner(evaluations: list[Evaluation]) -> Evaluation | None:
    """Return the first evaluation with verdict STOP_SUCCESS, or None.

    Preserves the order of `evaluations`, which is the spawn order — so
    early successful branches win and ties favour the first emitted.
    """
    for ev in evaluations:
        if ev.verdict is Verdict.STOP_SUCCESS:
            return ev
    return None


def _build_final_payload(outcomes: list[_TaskOutcome]) -> dict[str, Any]:
    """Assemble the user-facing final payload from per-task outcomes.

    Carries enough detail for the CLI (and any downstream consumer) to
    render a useful end-of-run report without re-querying the trace DB:

    - Per-task: verdict, iterations used, winner branch id, full
      metric breakdown, evaluator critique + weaknesses + suggestions.
    - Per-task: a ``winner_payload`` summary distilled from the winning
      branch's tool outputs (top designed sequence + score, predicted
      pLDDT/pTM, foldseek top hit if present, list of tools called).
    - Top-level ``description`` mirrors the original task description.
    """
    return {
        "tasks": [
            {
                "task_id": o.task.task_id,
                "description": o.task.description,
                "iterations_used": o.iterations_used,
                "winner_branch_id": o.winner.branch_id if o.winner else None,
                "verdict": o.evaluation.verdict.value if o.evaluation else "no_branches",
                "passed_metrics": (
                    [s.metric.value for s in o.evaluation.score.metric_scores if s.passed]
                    if o.evaluation
                    else []
                ),
                "metric_scores": (
                    [
                        {
                            "metric": s.metric.value,
                            "value": s.value,
                            "passed": s.passed,
                        }
                        for s in o.evaluation.score.metric_scores
                    ]
                    if o.evaluation
                    else []
                ),
                "summary": o.evaluation.critique.summary if o.evaluation else "",
                "weaknesses": (
                    list(o.evaluation.critique.weaknesses) if o.evaluation else []
                ),
                "suggestions": (
                    list(o.evaluation.critique.suggestions) if o.evaluation else []
                ),
                "winner_payload": (
                    _summarize_winner_payload(o.winner.payload) if o.winner else {}
                ),
            }
            for o in outcomes
        ],
    }


def _summarize_winner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Distill a winning branch's payload to fields a user actually wants.

    The raw payload mirrors every tool's full output; for an end-of-run
    report we only need the top backbone, top sequence, fold metrics,
    and the closest foldseek hit. Anything missing is omitted rather
    than emitted as None — keeps the JSON tidy.
    """
    out: dict[str, Any] = {"tools": sorted(k for k in payload if k != "fold")}

    rfd = payload.get("rfdiffusion3") or {}
    designs = rfd.get("designs") or []
    if designs:
        first = designs[0]
        out["top_backbone"] = {
            "design_id": first.get("design_id"),
            "pdb_path": first.get("pdb_path"),
            "plddt_estimate": first.get("plddt_estimate"),
        }
        out["num_backbones"] = len(designs)

    mpnn = payload.get("protein_mpnn") or {}
    sequences = mpnn.get("sequences") or []
    if sequences:
        # MPNN sorts ascending by score; lower = better.
        ranked = sorted(sequences, key=lambda s: s.get("score", float("inf")))
        out["top_sequence"] = {
            "sequence": ranked[0].get("sequence"),
            "score": ranked[0].get("score"),
        }
        out["num_sequences"] = len(sequences)

    fold = payload.get("fold") or payload.get("alphafold") or {}
    if fold:
        out["fold"] = {
            k: fold[k] for k in ("pdb_path", "plddt", "ptm") if k in fold
        }

    foldseek = payload.get("foldseek") or {}
    hits = foldseek.get("hits") or []
    if hits:
        top_hit = hits[0]
        out["foldseek_top_hit"] = {
            "target": top_hit.get("target"),
            "tm_score": top_hit.get("tm_score"),
            "evalue": top_hit.get("evalue"),
        }
        out["num_foldseek_hits"] = len(hits)

    return out

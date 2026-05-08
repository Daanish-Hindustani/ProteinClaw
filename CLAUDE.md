# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Phases 0–6 complete; Phase 7 (Evolution Service) is next.** `PLAN.md` is the authoritative roadmap; `PROJECT.md` is the component spec. Source lives under `src/proteinclaw/`. Real tool backends (RCSB / Foldseek / ESM Atlas REST + RFdiffusion / ProteinMPNN / ColabFold local) are wired behind env-var-driven factory selection (`PROTEINCLAW_BACKEND=auto`). Before scaffolding new components, confirm scope with the user.

## What this project is

A custom agentic workflow for **protein design**. The agent must reason through design tasks, branch into multiple exploration paths, evaluate results, learn from failures, and self-evolve its skills/tools. See `PROJECT.md` for the full component spec and end-to-end workflow, and `PLAN.md` for the implementation order.

## Layout

Standard Python `src` layout. Top-level package is `proteinclaw`; the seven components from PROJECT.md map to subpackages of identical names:

```
src/proteinclaw/
  common/          # logging + canonical TraceEvent (the trace bus everyone emits to)
  orchestrator/    # request parsing, task planning, k=3 iteration loop
  agents/          # Sub-Agent Branching Service
  tools/           # Tool Registry + base classes
    protein/       #   RFdiffusion3, ProteinMPNN, AlphaFold, Foldseek, RCSB wrappers
  skills/          # Skill Library (Markdown skills, SkillManager, validator)
    protein_design/  # seed skills: binder/enzyme/motif/hotspot
  evaluation/      # Evaluator + metrics
  memory/          # Knowledge / Session / Trace stores (SQLite + FTS5) + compaction
  evolution/       # Optimizer Protocol (Feedback Descent default, GEPA stub)
  sandbox/         # subprocess + rlimits Python runner
tests/             # mirrors src/proteinclaw/ subpackage layout, plus fixtures/
docs/              # architecture, formats, setup, examples — filled per phase
config/            # YAML thresholds, optimizer config
```

## Architecture (target)

The system is organized around seven cooperating components. Reading any one in isolation will mislead — they only make sense as a loop:

1. **Orchestrator** — parses the user request, decomposes it into tasks, dispatches to the branching service, consumes evaluator feedback, decides whether to iterate (cap **k=3**), and returns the final result.
2. **Sub-Agent Branching Service** — for each task, spawns multiple sub-agents exploring *different* reasoning paths (different hotspots, contigs, RFdiffusion params). Children may spawn their own children up to depth 2; backtrack from failed branches; return the best result per branch. Branching, not single-path execution, is the core value. Caps: fanout 3, depth 2, total 12 per session.
3. **Tool Registry** — single source of truth for tool names, schemas, examples, and runtime metrics. Wraps RFdiffusion3, ProteinMPNN, AlphaFold/ESMFold, Foldseek, RCSB, plus a Python sandbox for ad-hoc analysis.
4. **Skill Library** — reusable Markdown workflows for domain tasks (binder design, enzyme design, motif scaffolding, hotspot selection, …). Skills are *data*, not code; the Evolution Service rewrites them via `SkillManager.patch()` (default) or `.rewrite()`. A `SkillValidator` (schema + prompt-injection scan) gates every write.
5. **Evaluator** — scores candidates on confidence, interface quality, RMSD, clashes, binding metrics, novelty, and constraint satisfaction. Emits a `Score`, an `EvaluationVerdict` (retry/branch/stop), **and a textual `Critique`** (the high-bandwidth signal Feedback Descent consumes).
6. **Memory System** — three stores plus compaction: **Knowledge** (papers, tool docs, domain concepts, reflections), **Session** (live run state, branches), **Trace** (reasoning, tool calls, outcomes — FTS5-searchable). Traces feed the Evolution Service.
7. **Evolution Service** — reads traces and evaluator critiques to update skills and tool descriptions. Default optimizer: **Feedback Descent** (Lee, Boen, Finn 2025). GEPA kept as a swap-in behind the same `Optimizer` Protocol.

### Control flow

`User → Orchestrator → (decompose) → Branching Service → (parallel sub-agents calling Tools + Skills + sandbox) → Evaluator → Orchestrator (iterate ≤k or finish) → Memory → Evolution`

Every step writes to the Trace Store. **Failures must surface, not be swallowed** — the quality bar explicitly rejects silent skipping of failed tools.

## Conventions specific to this repo

- **Strict module boundaries.** A tool wrapper must not import from the orchestrator; the evaluator must not reach into memory internals — go through the public Protocol.
- **Every public class/function gets a docstring.** Explain *why*, not *what*. Google-style enforced by ruff `D`.
- **Immutable data by default.** Pydantic models with `model_config = ConfigDict(frozen=True, extra="forbid")` for domain types; return new copies, never mutate.
- **Async end-to-end.** All I/O (LLM, tools, DB) is `async`. Use `pytest-asyncio` (auto mode is on).
- **No silent failures.** Every error path raises a typed exception and emits a trace event with `EventKind.TOOL_FAILED` (or equivalent).
- **Mock expensive tools in CI.** Real RFdiffusion/AlphaFold runs are marked `@pytest.mark.expensive` and excluded from default `pytest`. Use fixtures under `tests/fixtures/`.
- **Traceability is a correctness requirement.** Code is not done unless its execution can be reconstructed from the Trace Store.
- **Canonical event kinds in `EventKind` only.** Never inline event-kind strings.

## Commands

```bash
uv sync --extra dev           # install + dev tooling
uv run pytest                  # mocked tests, coverage gate ≥80%
uv run pytest -m expensive     # real-tool tests (gated, opt-in; Phase 6+)
uv run ruff check src tests
uv run ruff format src tests
uv run mypy                    # strict, on src/proteinclaw
```

CI mirrors these (`.github/workflows/ci.yml`). Coverage gate fails the build below 80%.

## Reference

- `PLAN.md` — phased implementation roadmap (authoritative for build order).
- `PROJECT.md` — component responsibilities and the 8-stage workflow (authoritative on architecture).

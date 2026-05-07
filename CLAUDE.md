# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Spec-only repository.** No source, build system, or tests exist yet. The architecture is described in `PROJECT.md`; this file complements it. Before scaffolding code, confirm with the user — `CLAUDE.md`'s core principles say to consult before implementing large components.

## What this project is

A custom agentic workflow for **protein design**. The agent must reason through design tasks, branch into multiple exploration paths, evaluate results, learn from failures, and self-evolve its skills/tools. See `PROJECT.md` for the full component spec and end-to-end workflow.

## Architecture (target)

The system is organized around seven cooperating components. Reading any one in isolation will mislead — they only make sense as a loop:

1. **Orchestrator** (`src/orchestrator/`) — parses the user request, decomposes it into tasks, dispatches to the branching service, consumes evaluator feedback, decides whether to iterate (default cap **k=3**), and returns the final result.
2. **Sub-Agent Branching Service** (`src/agents/`) — for each task, spawns multiple sub-agents exploring *different* reasoning paths (different hotspots, contigs, RFdiffusion params, etc). Sub-agents may spawn children, backtrack from failed branches, and return the best result per branch. Branching, not single-path execution, is the core value.
3. **Tool Registry** (`src/tools/`) — single source of truth for tool names, schemas, examples, and runtime metrics. Wraps RFdiffusion3, ProteinMPNN, AlphaFold/ESMFold, Foldseek, RCSB, plus a Python sandbox for ad-hoc analysis.
4. **Skill Library** (`src/skills/`) — reusable Markdown workflows for domain tasks (binder design, enzyme design, motif scaffolding, hotspot selection, …). Skills are *data*, not code; the Evolution Service rewrites them.
5. **Evaluator** (`src/evaluation/`) — scores candidates on confidence, interface quality, RMSD, clashes, binding metrics, novelty, and constraint satisfaction. Emits the iterate/branch/stop signal.
6. **Memory System** (`src/memory/`) — three stores plus compaction: **Knowledge** (papers, tool docs, domain concepts), **Session** (live run state, branches), **Trace** (reasoning traces, tool calls, outcomes). Traces feed the Evolution Service.
7. **Evolution Service** (`src/evolution/`) — reads traces and evaluator feedback to update skills, tool descriptions, and planning heuristics. PROJECT.md specifies using **GEPA** (`https://gepa-ai.github.io/gepa/blog/2026/02/18/introducing-optimize-anything/`) — do not roll your own optimizer without consulting the user.

### Control flow

`User → Orchestrator → (decompose) → Branching Service → (parallel sub-agents calling Tools + Skills + sandbox) → Evaluator → Orchestrator (iterate ≤k or finish) → Memory → Evolution`

Every step writes to the Trace Store. **Failures must surface, not be swallowed** — quality bar in this repo explicitly rejects silent skipping of failed tools.

## Conventions specific to this repo

- **Modular files; no cross-component coupling.** The component boundaries above are load-bearing — a tool wrapper must not import from the orchestrator, etc.
- **Every public class/function gets a docstring.** Explain *why*, not what (see `CLAUDE.md` original example).
- **Mock expensive tools in CI.** RFdiffusion/AlphaFold runs are not allowed in the default test path; use fixtures (PDBs, tool outputs, evaluator outputs).
- **Traceability is a correctness requirement.** Code is not done unless its execution can be reconstructed from the Trace Store.

## Commands

None yet — no `pyproject.toml`, `package.json`, or test runner is configured. When you scaffold the first module, also add the build/test commands here.

## Reference

- `PROJECT.md` — full component responsibilities and the 8-stage workflow. Authoritative when this file and PROJECT.md disagree.

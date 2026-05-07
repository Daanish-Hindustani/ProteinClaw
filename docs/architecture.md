# Architecture

> Stub. Filled in Phase 8. See `PLAN.md` §4 and `PROJECT.md` for the current target architecture.

## Components

- Orchestrator
- Sub-Agent Branching Service
- Tool Registry
- Skill Library
- Evaluator
- Memory System
- Evolution Service

## Cross-cutting

- Trace Store as the single source of truth for execution replay.
- `Optimizer` Protocol with Feedback Descent default and GEPA swap-in.
- Strict module boundaries; no cross-component imports.

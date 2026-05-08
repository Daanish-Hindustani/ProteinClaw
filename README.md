# ProteinClaw

Agentic protein-design workflow with branching sub-agents, evaluation, memory, and self-evolution.

**Status:** Phases 0–6 complete (orchestrator, branching, tools, evaluator, memory, real backends). Phase 7 (Evolution Service) is next. See `PLAN.md` for the full roadmap and `PROJECT.md` for the component spec.

## Quick start

```bash
uv sync --extra dev
uv run pytest                  # runs against mocks; ~1 s
```

For real protein-design tools (RCSB / Foldseek / ESM Atlas / RFdiffusion / ProteinMPNN / ColabFold), see [`docs/setup.md`](docs/setup.md). For full GPU setup on Lambda Labs, see [`docs/lambda_labs.md`](docs/lambda_labs.md).

## Documentation

| Doc | Purpose |
|---|---|
| [`PROJECT.md`](PROJECT.md) | Component spec + 8-stage workflow (authoritative on architecture) |
| [`PLAN.md`](PLAN.md) | Phased implementation roadmap |
| [`CLAUDE.md`](CLAUDE.md) | Conventions + commands for Claude Code sessions |
| [`docs/setup.md`](docs/setup.md) | Backend selection, env vars, local install |
| [`docs/lambda_labs.md`](docs/lambda_labs.md) | GPU instance setup + manual smoke tests |
| [`docs/skill-format.md`](docs/skill-format.md) | Skill schema + validation |
| [`docs/eval-metrics.md`](docs/eval-metrics.md) | Evaluation metrics + verdict policy |
| [`docs/trace-format.md`](docs/trace-format.md) | TraceEvent shape + canonical event kinds |
| [`docs/memory-format.md`](docs/memory-format.md) | SQLite + FTS5 schemas |
| [`docs/tool-registry-format.md`](docs/tool-registry-format.md) | Tool registry surface + adding new tools |

# ProteinClaw — Implementation Plan

> Authoritative plan for building ProteinClaw, an agentic protein-design workflow.
> Companions: `PROJECT.md` (component spec), `CLAUDE.md` (conventions, target layout).
> Conflicts: `PROJECT.md` wins on architecture; this file wins on implementation order and tech choices.

## 1. Goal

Build a Python agent system that takes a natural-language protein-design request and drives it through an 8-stage loop:

```
intake → planning → branching sub-agents → tool/skill execution → evaluation
       → iteration (≤ k=3) → memory persistence → self-evolution
```

Output: final designs plus reasoning, files, and tool outputs, with the entire run reconstructable from the Trace Store.

## 2. Hard Constraints (from PROJECT.md and CLAUDE.md)

- Seven components with strict module boundaries; no cross-component imports beyond defined interfaces.
- Every public class/function has a docstring. Comments explain *why*, not *what*.
- Failures must surface — no silent skips of failed tools.
- All execution reconstructable from the Trace Store (traceability is a correctness requirement).
- Expensive tools (RFdiffusion3, ProteinMPNN, AlphaFold) mocked in CI; real runs gated.
- ≥ 80% test coverage on `src/` (excluding real-tool backends and `examples/`). Unit + integration + regression tests.
- Skills are data (Markdown), rewritten by the Evolution Service — not code.
- Iteration cap **k = 3** per task.
- Branching, not single-path execution, is the core value.
- Folder layout in CLAUDE.md is authoritative for module placement.

## 3. Tech Stack (Locked)

| Area | Choice |
|---|---|
| Language | Python 3.11+ |
| Package manager | `uv` |
| Validation | Pydantic v2 |
| Concurrency | `asyncio` end-to-end |
| LLM | `LLMClient` Protocol, `litellm` adapter, Claude as default; provider-agnostic |
| Storage | SQLite + FTS5 for Trace, Session, and Knowledge stores |
| Sandbox | `subprocess` + `resource` rlimits |
| Logging | `structlog` (JSON renderer) |
| Test | `pytest` + `pytest-asyncio` + `pytest-cov` (`--cov-fail-under=80`) |
| Lint / type | `ruff` + `mypy --strict` on `src/` |
| Optimizer | **Feedback Descent** (default), GEPA stub behind same `Optimizer` Protocol |

## 4. Architecture Patterns (Locked)

### 4.1 Branching limits (Hermes-validated)

- Max fanout: **3** concurrent children
- Max depth: **2** (parent → child, no grandchildren)
- Max total branches per session: **12**
- Iteration cap: **k = 3**

### 4.2 Subagent capability restrictions

Children of a sub-agent are denied (via `ToolPermissionSet` on branch context):

- recursive `delegate_task` (prevents exponential trees)
- `memory.write` (only the parent writes; eliminates concurrent state corruption)
- user-clarification tools (children cannot block on user input)
- cross-channel side effects

Children **retain** Python sandbox access — protein design needs ad-hoc analysis (RMSD, PDB parsing). Writes route through the parent.

### 4.3 Skills

- Markdown files under `src/skills/protein_design/` with front-matter (id, version, applicable_tasks, examples, provenance).
- `SkillManager` exposes `create | edit | patch | delete` actions (Hermes pattern).
- `patch` (targeted find-and-replace) is the default action for evolution; `rewrite` is the fallback.
- **`SkillValidator` runs before any skill enters the library** — schema check + prompt-injection threat scan. Required path for both human-authored and agent-authored skills.

### 4.4 Memory model

| Store | Purpose | Backend |
|---|---|---|
| Knowledge Store | Curated domain knowledge (papers, tool docs, reflections) | SQLite + FTS5 |
| Session Store | Live run state, active branches | SQLite |
| Trace Store | Raw events: reasoning, tool calls, branch decisions, outcomes | SQLite + FTS5, append-only |

A **reflections table** in Knowledge Store holds short curated lessons written by the Evolution Service — input material for the optimizer.

### 4.5 Trace compaction

Compaction uses a structured template (Hermes pattern), not free-form summarization:

```
Goal | Progress | Decisions | Files | Next Steps
```

Triggered above a size threshold; preserves high-value events (failures, evaluator verdicts, branch winners) verbatim.

### 4.6 Prompt cache

Frozen system-prompt snapshot at session start (Knowledge metadata + active skill list) so live changes do not invalidate Anthropic's prompt cache mid-session.

### 4.7 Self-evolution

`Optimizer` Protocol with two implementations:

- `FeedbackDescentOptimizer` (default) — pairwise comparison + textual critiques drive edits. ~100–150 LoC.
- `GEPAOptimizer` (stub) — wired so a future `pip install gepa` plus ~50 LoC flips it on without touching callers.

**Eval source for the optimizer: live runs.** Real user requests serve as eval tasks; two skill versions race in parallel branches, the comparator's critique drives the edit. *Revisit at Phase 7 — may add a small fixture seed set then.*

Skill rewrites: **auto-promote with versioned rollback.** Old versions remain diffable in the database.

## 5. Phased Implementation

End-to-end mocked demo achievable after Phase 4 (~6 days). Full system with real tools + Feedback Descent optimizer: ~11–14 working days.

| # | Phase | Size | Effort |
|---|---|---|---|
| 0 | Bootstrap | S | 0.5 d |
| 1 | Core types + Trace/Session stores | M | 1 d |
| 2 | Tool Registry + mock tools + sandbox | M | 1.5 d |
| 3 | Skill Library + Evaluator skeleton | M | 1 d |
| 4 | Branching Service + Orchestrator | L | 2 d |
| 5 | Memory hardening + compaction | M | 1 d |
| 6 | Real skill content + real tool backends | L | 2–4 d |
| 6.5 | CLI + AI integration (interactive setup, doctor, run) | M | 1 d |
| 7 | Evolution Service via Feedback Descent — **PAUSED** | M | 1 d (+ 0.5 d GEPA stub) |
| 8 | Polish, docs, examples | S | 1 d |

**Phase 7 status:** paused. Decision is to ship a runnable CLI with AI integration first so the user can drive real end-to-end queries before we tackle self-evolution. Phase 6.5 inserted to track that work; Phase 7 resumes after.

---

### Phase 0 — Bootstrap

Foundation only, no business logic.

- `pyproject.toml` with `uv`, Python ≥ 3.11, deps: pydantic v2, structlog, litellm, sqlite (stdlib), pytest stack, ruff, mypy.
- `src/` package skeleton matching CLAUDE.md folder layout; each subpackage has `__init__.py` + module docstring.
- `src/common/logging.py` — structured logger and `TraceEvent` dataclass stub that every component will emit to.
- CI (GitHub Actions): lint (ruff), type-check (mypy strict on `src/`), test (`pytest --cov-fail-under=80`), `@pytest.mark.expensive` excluded by default.
- `docs/` empty stubs: architecture, tool-registry-format, skill-format, memory-format, trace-format, eval-metrics, setup, examples.

**Risk:** Low. **Dependencies:** none.

---

### Phase 1 — Core domain types and Trace Store

The data model that every other component speaks in.

- `src/orchestrator/task.py` — `Task`, `TaskStatus`, `SuccessCriterion`, `TaskResult` (immutable Pydantic models / frozen dataclasses).
- `src/agents/branch_result.py` — `BranchResult`, `BranchId`, `BranchStatus`. **`BranchResult` records `skill_version_id`** (raw material for live-run evolution).
- `src/evaluation/scoring.py` — `Score`, `EvaluationVerdict` (retry/branch/stop), `Metric` enum, `Critique` (text feedback for Feedback Descent).
- `src/memory/trace_store.py` — append-only `TraceEvent` records (timestamp, component, branch_id, parent_id, event_type, payload). Behind a `TraceStore` Protocol; first impl JSONL + in-memory; SQLite + FTS5 in Phase 5.
- `src/memory/session_store.py` — live run state keyed by `session_id`; immutable updates returning new state.
- Tests: round-trip serialization, trace replay reconstructs session state, immutability invariants.

**Risk:** Medium — getting these types wrong forces rewrites. Short design review before coding.
**Dependencies:** Phase 0.

---

### Phase 2 — Tool Registry, mock tools, and Python sandbox

- `src/tools/base_tool.py` — `BaseTool` ABC: `name`, `description`, `input_schema` (Pydantic), `output_schema`, `examples`, `run(input) -> ToolOutput`. `ToolOutput`: status, payload, stderr, metrics. Errors raise typed `ToolExecutionError` — registry catches and records as a trace event. **No silent failures.**
- `src/tools/registry.py` — `register`, `find_by_name`, `describe_all`, `record_invocation` (tracks performance per spec).
- `src/tools/protein/` — wrappers delegate to a swappable `Backend` (real vs mock). Mock backends first:
  - `rfdiffusion3.py`, `protein_mpnn.py`, `alphafold.py` (with ESMFold alt), `foldseek.py`, `rcsb.py`.
- `src/sandbox/python_runner.py` — restricted subprocess with timeout + memory cap (`resource` rlimits), captures stdout/stderr/return.
- `tests/fixtures/` — sample PDBs, mock RFdiffusion outputs, mock AlphaFold pLDDT JSON, mock Foldseek hits.
- Tests: schema validation, registry round-trip, mock determinism, sandbox enforcement, error surfacing (failed tool → `ToolExecutionError` + trace event, never silent skip).

**Risk:** Medium for sandbox security; low otherwise.
**Dependencies:** Phase 1.

---

### Phase 3 — Skill Library and Evaluator skeleton

- `src/skills/skill.py` — `Skill` Pydantic model: id, name, description, applicable_tasks, markdown_body, examples, version, provenance.
- `src/skills/skill_library.py` — load/list/search; `find_skills_for(task)` returns ranked candidates (keyword + tag match initially).
- `src/skills/skill_validator.py` — schema check + prompt-injection threat scan. Required gate before persistence.
- `src/skills/protein_design/*.md` — placeholder seed skills: binder_design, enzyme_design, motif_scaffolding, hotspot_selection. Real content in Phase 6.
- `src/evaluation/metrics.py` — concrete metrics: RMSD, clash score, interface SASA, pLDDT/pTM extraction, novelty (via Foldseek mock). Pure functions with fixture-driven tests.
- `src/evaluation/evaluator.py` — composes metrics into `Score`, applies thresholds, emits `EvaluationVerdict`, **and a textual `Critique`** (input for Feedback Descent in Phase 7). Thresholds in YAML — no magic numbers.
- Tests: deterministic metric outputs, verdict thresholds, skill load/search, validator rejects malicious skills.

**Risk:** Medium — metric correctness is domain-sensitive; pin behavior with golden-file tests.
**Dependencies:** Phase 1, Phase 2.

---

### Phase 4 — Sub-Agent Branching Service and Orchestrator

End-to-end skeleton runs after this phase using mock tools.

- `src/agents/sub_agent.py` — runs one branch: select skill → select tools → execute → produce `BranchResult`. Injected `LLMClient`. **Carries a `ToolPermissionSet`** restricting children per §4.2.
- `src/agents/branching_service.py` — `explore(task, fanout, max_depth)`. Emits trace events for spawn/backtrack/completion. Hard caps: fanout 3, depth 2, total 12. Backtracks on `BranchStatus.FAILED` or low score. **Branch context binds a specific `skill_version_id`** (enables A/B in Phase 7).
- `src/orchestrator/planner.py` — decomposes user request into `Task` list. LLM with structured output (Pydantic schema); hardcoded fallback for tests.
- `src/orchestrator/orchestrator.py` — full loop: intake → clarify (interactive CLI prompt) → plan → dispatch each task to BranchingService → collect → Evaluator → iterate up to `MAX_ITERATIONS = 3` → assemble final response.
- `LLMClient` writes a frozen system-prompt snapshot at session start (prompt cache hit).
- Integration test: full pipeline on a mocked binder-design prompt — task decomposition, ≥ 2 branches per task, evaluator runs, iteration ≤ 3, non-empty result, full trace replays cleanly.

**Risk:** High — branching state, LLM cost, trace volume first appear here. Mitigated by hard caps and an LLM stub for tests.
**Dependencies:** Phases 1–3.

---

### Phase 5 — Memory hardening and compaction

- `src/memory/knowledge_store.py` — papers, tool docs, domain concepts, **reflections table**. Keyword + FTS5 retrieval first; embeddings deferred.
- Persistent `TraceStore` and `SessionStore` — swap JSONL/in-memory for SQLite + FTS5 behind the Protocols established in Phase 1.
- `src/memory/compaction.py` — collapses long traces using the `Goal | Progress | Decisions | Files | Next Steps` template. Preserves failures, verdicts, branch winners verbatim. Triggered above a size threshold.
- `src/memory/memory_manager.py` — facade unifying the three stores: `recall(query, store)`, `record(event)`.
- Tests: compaction preserves required event types, persistence round-trips, FTS5 recall on fixtures.

**Risk:** Medium — trace volume and compaction LLM cost. Mitigate with size-threshold triggers.
**Dependencies:** Phase 4.

---

### Phase 6 — Real skill content and real tool backends (gated)

- **Reference**: https://github.com/jasonkim8652/protein-design-mcp — consult before writing real backends; mirror its integration patterns, env requirements, and parameter conventions.
- Author real Markdown skills for binder/enzyme/motif/hotspot with literature-grounded examples.
- Real tool backends behind feature flags / env vars, easiest first:
  1. RCSB (REST), Foldseek (REST or local).
  2. ESMFold via API.
  3. AlphaFold local or Colabfold (heavy; conda env documented).
  4. RFdiffusion3, ProteinMPNN (heavy; conda env documented).
- All real-backend tests marked `@pytest.mark.expensive`; nightly job, not PR CI.
- **Note:** local execution for now. Future: remote-API backend (NIM, Tamarind, etc.) drops in via the existing `Backend` abstraction without touching tool wrappers.

**Risk:** High — CUDA, conda, large weights. Mitigated by `Backend` boundary and mocks-as-default.
**Dependencies:** Phase 2 boundary; can run parallel to Phase 7.

---

### Phase 7 — Evolution Service via Feedback Descent

- `src/evolution/optimizer.py` — `Optimizer` Protocol: `optimize(seed_candidate, dataset, evaluator) -> OptimizationResult`. Result shape uniform across implementations: `best_candidate`, `score_history`, `lineage`.
- `src/evolution/feedback_descent.py` — default. Loop:
  ```
  pair candidates → evaluator.compare(a, b) → (winner, critique)
                  → editor_lm.propose_edit(winner, critique)
                  → score-gated accept
  ```
  ~100–150 LoC.
- `src/evolution/gepa_optimizer.py` — stub class with `NotImplementedError` and a TODO. Future `pip install gepa` + ~50 LoC flips it on; no caller changes.
- `src/evolution/mistake_tracker.py` — aggregates failure patterns from traces (which tool, which params, which metric tanked).
- `src/evolution/skill_writer.py` — applies skill edits via `SkillManager.patch()` (default) or `.rewrite()` (fallback). Versioned, diffable, auto-promote with rollback.
- `src/evolution/evolution_service.py` — orchestrates: read traces → mistake_tracker → optimizer → skill_writer. Records evolution events in trace store.
- **Eval source: live runs.** Branch context already binds `skill_version_id` (Phase 4) — A/B comparison uses real user tasks. *Revisit at start of phase: do we want a small fixture seed set?*
- Tests: synthetic failure trace produces a specific skill edit (golden file); idempotency on no-op runs; optimizer Protocol contract tests inherited by both implementations.

**Risk:** Medium — Feedback Descent has no published package; we implement from the paper. ~100–150 LoC is realistic; read full PDF before locking prompt templates for editor and comparator.
**Dependencies:** Phase 5 (trace history), Phase 3 (skills + evaluator critiques).

---

### Phase 8 — Polish, docs, examples, CLI

- End-to-end example notebooks under `examples/` for binder design, enzyme stability, motif scaffold.
- Fill all `docs/` stubs created in Phase 0.
- Coverage audit; raise any module below 80%.
- `proteinclaw run --prompt "..."` CLI entrypoint.

**Risk:** Low.

## 6. Risks (Tracked Across Phases)

- **External tool environments (HIGH)** — CUDA/conda/large weights for RFdiffusion, AlphaFold. Mitigated by `Backend` abstraction; default install ships mocks only.
- **Branching state explosion (HIGH)** — child sub-agents recursively spawning. Capped: fanout 3, depth 2, total 12, plus early-stop on low evaluator score.
- **LLM cost in branching (HIGH)** — fanout × tasks × iterations × sub-calls. Mitigated by tiered model routing (planner/orchestrator strong; per-branch reasoning cheap), prompt caching, token usage recorded in traces.
- **Trace store volume (MEDIUM)** — large LLM-heavy runs. Mitigated by structured event types, compaction (Phase 5), SQLite indexing.
- **Evaluator subjectivity (MEDIUM)** — bad thresholds cause infinite iteration up to k=3. Mitigated by golden-file tests and YAML-tunable thresholds.
- **Sandbox security (MEDIUM)** — running LLM-written Python. Mitigated by `subprocess` + rlimits; revisit if exposed beyond trusted dev use.
- **Feedback Descent implementation risk (MEDIUM)** — no reference package. Read full paper before Phase 7 to lock prompt templates.

## 7. Open Items

These are deliberately deferred; revisit at the marked phase.

- **Phase 7 — eval source for the optimizer.** Locked as live runs for now; user wants to revisit at the start of Phase 7 (small fixture seed set vs. pure live).
- **Real tool deployment.** Local for Phase 6; remote API backends (NIM, Tamarind, etc.) planned post-Phase 6 via the same `Backend` abstraction.
- **GEPA swap.** Stub in place; flip when a future need surfaces.

## 8. Done Criteria

A phase is done when:

- All listed deliverables exist.
- Tests pass with ≥ 80% coverage on the modules touched.
- Trace events emit cleanly for every component path.
- No silent failures (every error path emits a typed exception and a trace event).
- New public surface is documented (docstrings + relevant `docs/` stub filled in).
- `ruff` and `mypy --strict` clean on `src/`.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session memory — read `NOTES.md` first, write to it on the way out

**Every session in this repo must:**

1. **At session start:** read `NOTES.md` in full before touching code. It is the canonical cross-session notebook — fixes, gotchas, pinned-version reasons, partial-implementation status, failed approaches. Skipping it means re-debugging things the previous session already solved.
2. **During work:** if you discover a non-obvious fact (a footgun, a fix, a pinned version, a decision worth preserving, a workaround for a tool quirk), append it to the correct section of `NOTES.md` immediately — don't wait until "the end."
3. **At session end:** scan what you did this session. Anything the next session would benefit from knowing that **isn't already** in PRD / ARCHITECTURE / PLAN / README / git log → append it to `NOTES.md`.

Format and rules (entry template, what belongs vs what doesn't, append-only convention) live at the top of `NOTES.md`. Follow them.

`NOTES.md` is **append-only**. Never delete or rewrite past entries — strike through with `~~text~~` and add a follow-up entry if something turns out to be wrong. The history of wrong turns is itself useful context.

`NOTES.md` is not a replacement for `DEBUG.md` (active debugging, per the "Debug workflow" section below). A debug entry moves from `DEBUG.md` → `NOTES.md` once it's resolved and the resolution is worth preserving.

## Project status

**Phases 1–8 of PRD §13 have landed** on `development`. End-to-end pipeline functional on a single A100. Honest snapshot:

| Phase | What's in | Notes |
|---|---|---|
| 1 — Skeleton | Registry + ComputeRouter + LocalRunner + doctor + smoke tool | All ✓ |
| 2/3 — Data + research tools | uniprot, pdb, rcsb, literature, web (all plain Python) | All ✓ |
| 4 — Model wrappers | ProteinMPNN, ESMFold, RFdiffusion3 (RFD3 via `rc-foundry[rfd3]`), AF2-multimer (via ColabFold) | All 4 Docker images built, E2E green individually |
| 5 — Agent core | `agent/{skills,trace,mcp_tools,core}.py`, `cli.py:run` wired, skill file v2 | ✓ |
| 6 — Triage + HTML report | `agent/triage.py`, `report.py` (Mol* viewer + scatter), result.json + designs dir | ✓ |
| 7 — SQLite persistence | `db.py`, `proteinclaw history`, `proteinclaw show` | ✓ |
| 8 — `--rounds` iteration | per-run system-prompt addendum + CLI flag | ✓ |
| 9 — Polish + docs | README quick-start, CLAUDE.md status (this section) | In progress |

When implementing, treat the PRD as the spec of record and follow its conventions verbatim — the §9 "Implementation" section is normative. Read `NOTES.md` for cross-session footguns and corrections.

## What `proteinclaw` is

A Python library + CLI: a Claude-powered agent (via the Claude Agent SDK, billed against the user's Claude Pro/Max subscription credit pool) that takes a natural-language binder-design prompt and autonomously runs the pipeline **RFdiffusion3 → ProteinMPNN → ESMFold (fast monomer pre-filter) → AlphaFold2-multimer (binder+target complex, the ranking signal)** on a local GPU workstation, then emits ranked PDBs/sequences and an HTML report.

Ranking signal = **AF2-multimer complex pLDDT averaged over the binder chain** (not monomer pLDDT). ESMFold is *only* a cheap pre-filter; the agent picks its own discard threshold per round and logs it.

## Planned layout (see PRD §9.1)

```
src/proteinclaw/
  agent/          # Claude Agent SDK loop + planner + skill loader
  tools/
    __init__.py            # ToolRegistry + @register
    _container_tools.py    # auto-discovery of tool.yaml
    rfdiffusion3/  proteinmpnn/  esmfold/  alphafold2_multimer/   # GPU tools (Docker)
    uniprot.py  pdb.py  rcsb.py  literature.py  pubmed.py   # plain-Python tools
    # NOTE: the PRD §9.1 `web.py` (DuckDuckGo) and `sandbox_exec.py` were NOT built.
    # Web search is served by the SDK's built-in WebFetch/WebSearch; literature
    # research is literature.py (LitSense) + pubmed.py. Glue-code execution uses the
    # SDK's built-in Bash (scoped to ./scratch/), not a RestrictedPython sandbox_exec.
  runner/local.py          # LocalRunner: Docker dispatcher
  runner/router.py         # ComputeRouter: local-only, VRAM checks
  skills/proteindesign.md       # core skill — concatenated into the system prompt every run
  skills/tools/<tool>.md        # per-tool detail — Read on demand by the agent (progressive disclosure)
  cli.py
```

## Conventions that are load-bearing

### 4-file-per-tool (MANDATORY for every GPU model) — PRD §9.2

Each model tool directory contains **four required files**: `tool.yaml`, `Dockerfile`, `implementation.py`, `tool_entrypoint.py`. Adding a new model = creating one directory; no other code edits. Auto-discovery picks it up. `tool_entrypoint.py` is **identical across every tool** (copy-paste the shim from §9.2).

In practice each model dir also carries a fifth helper, `_normalize.py` (parameter/PDB normalisation extracted so host-side unit tests can import it **without** triggering the container-only imports in `implementation.py`). This is an allowed, deliberate exception to "four files" — see the 2026-05-23 `_normalize.py` NOTES entry. Tests must load it via `importlib.util.spec_from_file_location` under a unique module name to avoid cross-tool name collisions.

`tool.yaml` is the single source of truth: agent-facing description, JSON-Schema parameter validation, and compute requirements (`requires_gpu`, `min_vram_gb`, `gpu_profile`, `timeout_s`).

### Session-keyed workspace, not bytes in JSON — PRD §9.3

Every run gets a `session_id`. Host mounts `~/.proteinclaw/gpu-workspace/<session_id>/` → `/workspace` in every container. Tools write artifacts to `/workspace/<tool>_<step>/` and return **paths** in the JSON envelope. **Never return PDB bytes through the LLM context.** One tool's output paths become the next tool's input paths.

### Uniform result envelope

Success: `{summary, metrics, session_id, ...tool-specific}`. Error: `{summary: "Error: ...", error, metrics}`. `summary` and `metrics` (vram before/peak, time) are required for GPU tools.

### Sandbox model

The Claude agent runs via the **Claude Agent SDK** (`claude-agent-sdk`). Tools are exposed via an in-process MCP server (`create_sdk_mcp_server` + `@tool` decorators wrapping our existing `registry.route()` calls). For autonomous runs, `permission_mode="bypassPermissions"` so the SDK doesn't prompt per tool call; the agent's outbound surface is the registered tool set + its own internal reasoning. GPU models dispatch via the same `ComputeRouter` → `LocalRunner` → `docker run --gpus all` chain. RestrictedPython remains available for any glue-code execution we don't want flowing through the SDK directly.

### Skill files: lean core in the system prompt, per-tool detail on demand

`proteinclaw/skills/proteindesign.md` is the **core** skill — **concatenated into the agent's system prompt at start of every run** (not a tool result, not lazy-loaded). It carries the pipeline overview, cardinal rules, the research/debate/hypothesis workflow, hotspot strategy, triage, and the self-refining loop. Editing it is the supported way to change agent behavior without code changes.

Per-tool operational detail (steps 4–7: RFD3, ProteinMPNN, ESMFold, AF2) lives in `skills/tools/<tool>.md` and is **progressively disclosed** — the core skill only summarises each step, and `agent/skills.py:load_skill_text()` appends a **Tool skill index** of absolute paths so the agent `Read`s the relevant file on demand before each step (its cwd is the run dir, so the index uses absolute paths). A cardinal rule enforces "Read the tool skill file before each tool step." `load_skill_text()` fails loud if the core file *or* the `tools/` dir is missing/empty. Antibody-design content (RFantibody/ANARCI/IMGT, scFv/VHH) was removed — out of scope for the de-novo mini-binder pipeline.

The agent's per-run notebook is `runs/<id>/plan.md` (cwd-relative `plan.md`): notes, reasoning, scout hypotheses, the debate log, and the converged design hypothesis. The skill (§1.7) tells the agent to `Write` it; `core.py` seeds it with a template and an honest "if this seed survives, the agent never reached deliberation" note (it no longer claims to be a layout placeholder).

### Failure mode: fail fast, log everything

- No silent fallbacks to degraded pipelines. If RCSB target resolution fails, the run fails with a clear error (no AlphaFold DB fallback in v1).
- Every agent decision + tool call goes to `trace.jsonl`. `--show-reasoning` surfaces it into the HTML report.
- No `--seed` flag. Reproducibility artifact is the trace, not a seed (the Claude plan is non-deterministic by design).

### Target-resolution is the *only* allowed interactive interruption

The agent proceeds on best-guess for most ambiguity and logs assumptions. If a target name maps to genuinely distinct biological entities (multiple isoforms / unrelated PDB structures), it asks **one** clarifying question with a numbered menu. Nothing else may prompt the user mid-run.

## CLI surface (PRD §11)

```
proteinclaw run "<prompt>" [--rounds N=12] [--no-cap] [--max-turns N=60] [--output-dir PATH]
                           [--model ID] [--research-fanout/--no-research-fanout]
                           [--dry-run] [--show-reasoning] [--skip-doctor]
proteinclaw history [--limit N] [--target X]
proteinclaw show <run_id>           # opens report.html
proteinclaw cancel <run_id>         # docker-kills the run's labelled containers, SIGTERMs its driver pid, marks 'cancelled'
proteinclaw doctor                  # GPU, Docker, weights, deps, disk checks
proteinclaw doctor --self-test      # full tool-level integration suite
```

`--rounds` defaults to **12** (range 1–50); `--no-cap` lifts the ceiling and lets the agent
self-pace against its quality gate. There is **no `--max-designs` flag** — the agent picks batch
sizes itself. `proteinclaw doctor` must pass before `proteinclaw run` is allowed (bypass with
`--skip-doctor`, dev/test only).

## Tests

Per PRD §10: tool-level integration tests live next to each tool, marked `@pytest.mark.gpu`, skipped by default, run on a GPU-enabled runner in CI. `proteinclaw doctor --self-test` is the user-facing "is my install healthy" entry point and runs the same suite end-to-end.

## Persistence

SQLite at `~/.proteinclaw/runs.db` with tables `runs`, `designs`, `agent_steps` (schema in PRD §6.9). `runs.target_pdb_id`, `target_chain`, `target_crop` capture target resolution; top pLDDT is **not** denormalized — derive from `designs.plddt_af2_complex`.

## VRAM floors (must match `tool.yaml` and `doctor`)

| Tool | `min_vram_gb` |
|---|---|
| `design.rfdiffusion3` | 22 |
| `design.proteinmpnn` | 12 |
| `structure.esmfold` | 16 |
| `structure.alphafold2_multimer` | 22 (40+ recommended for complexes >400 residues) |

## Phased build order — PRD §13

Land in order; Task 1 unblocks all others.

1. Tool-wrapper skeleton + registry + auto-discovery + `LocalRunner` + `ComputeRouter` + `doctor`, proven end-to-end with one trivial GPU tool.
2. `uniprot` / `pdb` / `rcsb` data tools.
3. Research tools: `literature.py` (LitSense) + `pubmed.py`. (PRD originally specified `web.py`/DuckDuckGo + Semantic Scholar; as built, general web search is served by the SDK's built-in WebFetch/WebSearch instead.)
4. RFdiffusion3 → ProteinMPNN → ESMFold → AF2-multimer wrappers (one at a time, each fully tested before the next).
5. Agent core (Claude Agent SDK wiring, skill-file loader as `append` system prompt, in-process MCP server wrapping all registered tools, the SDK's built-in Bash scoped to `./scratch/` for non-tool glue — the PRD's `sandbox_exec` RestrictedPython tool was not built).
6. Triage + ranking + HTML report.
7. SQLite persistence + `history` / `show`.
8. Iteration logic (`--rounds`).
9. Polish + docs.

When implementing any tool, **read PRD §9 in full** before writing code — the conventions there are non-negotiable.

## Development workflow

For every non-trivial change, follow this order. Do not skip steps; do not collapse them.

1. **Plan** — restate the requirement, list affected files, call out risks and unknowns. Use the **planner** agent for anything spanning multiple modules.
2. **Design** — sketch the interface (function signatures, JSON Schema for `tool.yaml`, data flow) before writing the body. For new tools, the design *is* `tool.yaml` + the `run()` signature.
3. **Test** — write tests first (RED). Tool-level integration tests live next to each tool and are marked `@pytest.mark.gpu`. Target 80%+ coverage.
4. **Implement** — minimal code to turn tests GREEN. No speculative generality, no half-finished branches.
5. **Manually test** — actually invoke the CLI / tool against a real input (e.g., the canonical PD-L1 prompt for end-to-end work, or a fixture PDB for a single tool). Type checks and unit tests verify correctness, not feature behavior — if you can't manually test it, say so explicitly.
6. **Repeat** — if manual testing surfaces a gap, loop back to step 1 for that gap. Don't patch over symptoms.
7. **Code review** — use the **code-reviewer** agent (and **security-reviewer** for anything touching the sandbox, Docker dispatch, or external APIs) before considering the change done.
8. **Update docs** — refresh `PRD-proteinclaw.md` only when the spec actually changed; refresh `proteindesign.md` when agent behavior changed; refresh this `CLAUDE.md` when a load-bearing convention changed. Stale docs are worse than missing docs.

## Code quality (non-negotiable)

Follow the global rules already in scope (`~/.claude/rules/ecc/common/`): immutability, KISS / DRY / YAGNI, small focused files (<800 lines, <50-line functions), explicit error handling, no magic numbers, validate at system boundaries, no hardcoded secrets. The PRD's "fail fast and loud" rule overrides any instinct to add silent fallbacks.

## Keep changes modular and tested

Every change should be a small, independently testable unit. Concretely:

- **One concern per change.** A new tool wrapper, a router fix, and a CLI flag are three changes, not one. Don't bundle unrelated edits into a single commit or PR.
- **Modularity follows the 4-file convention.** New models go in their own `tools/<name>/` directory. New plain-Python tools are single files. Don't reach across tool boundaries — share via the registry and the `/workspace` session directory, not via cross-imports.
- **Every module ships with its tests.** Plain-Python tools get unit tests next to them; GPU tools get `@pytest.mark.gpu` integration tests next to them. No untested code lands, even behind a feature flag.
- **Public seams stay narrow.** Tools expose `run(**kwargs) -> dict`. The registry exposes lookup + dispatch. The router exposes `route()`. Don't widen these interfaces to paper over a leaky abstraction — fix the abstraction.
- **Refactors are their own change.** If a refactor is needed to land a feature cleanly, do the refactor first as a separate, test-passing change, then build the feature on top.

If a change can't be made modular and tested at the size you're attempting, the change is too big — split it.

## Honesty about implementation state

**Never overstate what is implemented.** This is the single most important rule when reporting status.

- If a function is stubbed, say "stubbed — returns a placeholder."
- If a tool's Docker image isn't built yet, say so; do not claim the dispatch path works end-to-end.
- If tests pass but you haven't manually verified the feature, say "tests pass; not manually verified."
- If something is broken, name the failure mode and what you tried, not "mostly works."
- If you skipped a step in the workflow above, name which step and why.

Bias toward under-claiming. A truthful "Task 4 lands the wrapper but AF2 OOMs on targets >400 residues — not yet handled" is far more useful than an optimistic summary that future-you (or a teammate) has to unwind.

## Debug workflow

When something breaks, follow this loop instead of guessing:

1. **Identify the issue precisely.** Capture the exact error string, the failing command, the input that triggered it, and the relevant `trace.jsonl` slice. Distinguish symptom from root cause — a `CUDA OOM` may be an oversized complex, a leaked allocation, or a missing batch-size cap.
2. **Write a failing test that captures the error.** Even for one-off bugs. The test should fail today with the same signature you see in production. This is what proves the fix later.
3. **Web search before guessing.** For unknown errors, conflicting docs, or "is this approach sound" moments, run a `WebSearch` (or `WebFetch` against the upstream repo / vendor docs) before proposing a fix. Searching the exact error string with the platform/version context is usually faster than reasoning from first principles. See the global decision-under-uncertainty rule — don't burn an hour guessing when one search would resolve it.
4. **Record in `DEBUG.md`** at the repo root. Append a dated entry per issue:

   ```markdown
   ## YYYY-MM-DD — <one-line title>
   **Symptom:** exact error / observed behavior
   **Repro:** minimal command or test that triggers it
   **Hypotheses tried:**
   - <approach> — outcome (why it didn't work)
   - <approach> — outcome
   **Resolution (if found):** what fixed it + link to commit / PR
   **Open questions:** anything still unknown
   ```

   Update the same entry as you learn more — don't start a new entry per attempt. If the issue is resolved, leave the entry in place; future debugging benefits from seeing what was already ruled out.
5. **Fix the root cause, not the symptom.** If the test from step 2 passes only because you bypassed a check, you haven't fixed it.
6. **Run the failing test from step 2 plus the full suite** before declaring done.

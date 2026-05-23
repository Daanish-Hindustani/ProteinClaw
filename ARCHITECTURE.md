# ARCHITECTURE.md — `proteinclaw`

**Status:** v1.0.0
**Scope:** How the pieces fit together, why they're shaped that way, and where the seams are.
**Read first:** `PRD-proteinclaw.md` §9 (Implementation) is normative; this document explains and connects it. When this doc and the PRD disagree, the PRD wins.

---

## 1. One-paragraph overview

`proteinclaw` is a Python CLI that turns a natural-language binder-design prompt into a ranked set of binder candidates. A Claude-backed agent (via the **Claude Agent SDK**, billed against the user's Claude Pro/Max subscription credit pool) drives the campaign through an in-process MCP server that wraps our tool registry, dispatching GPU-heavy model calls (RFdiffusion3, ProteinMPNN, ESMFold, AlphaFold2-multimer) out to **local Docker containers** via a `ComputeRouter` → `LocalRunner` chain. Tools share state through a per-run **session workspace** mounted into every container; they pass *paths*, never multi-MB PDB bytes, through the LLM context. Designs are ranked by **AF2-multimer complex pLDDT averaged over the binder chain**; ESMFold is only a fast monomer pre-filter the agent uses to discard non-folders before the expensive AF2 step.

---

## 2. Layered view

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 5: CLI                              proteinclaw run / doctor / │
│                                           history / show / cancel    │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 4: Agent Core                       Claude Agent SDK + skill   │
│                                           loader + in-process MCP    │
│                                           + trace.jsonl writer       │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 3: Sandbox                          RestrictedPython exec env  │
│                                           (parsing, glue, NO models) │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 2: Tool Registry + Router           registry  →  ComputeRouter │
│                                                       →  LocalRunner │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 1: Tools                                                       │
│   Plain-Python (in-process):  uniprot, pdb, rcsb, literature, web   │
│   GPU (Docker):  rfdiffusion3, proteinmpnn, esmfold, af2_multimer    │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 0: Persistence                      SQLite (~/.proteinclaw/    │
│                                           runs.db) + session         │
│                                           workspace + weight caches  │
└──────────────────────────────────────────────────────────────────────┘
```

Arrows in this stack point downward only. The agent never reaches past the registry to a tool's internals; the runner never reaches up to the agent. Each seam is narrow on purpose (§6).

---

## 3. Process / container topology

```
HOST process (proteinclaw CLI)
├── Python runtime
│   ├── Claude Agent SDK loop (`claude_agent_sdk.query` / `ClaudeSDKClient`)
│   ├── RestrictedPython sandbox
│   │   └── calls registered tool functions
│   │       ├── plain-Python tools run HERE (in-process)
│   │       └── GPU tools call router → LocalRunner
│   ├── SQLite writer  (~/.proteinclaw/runs.db)
│   └── trace.jsonl appender
│
└── Docker (one container per GPU tool invocation)
    ├── /workspace  ← bind-mounted from
    │                  ~/.proteinclaw/gpu-workspace/<session_id>/
    ├── /root/.cache/{huggingface,rfdiffusion,proteinmpnn,openfold}
    │                ← bind-mounted from host caches
    ├── tool_entrypoint.py  (universal shim, identical per tool)
    └── implementation.py   (the actual model wrapper)
```

The host is the only long-lived process. Each GPU container is **single-purpose, single-use**: spun up for one `run()` call and torn down. The container has no knowledge of the agent, the registry, or other tools — it only knows "read `input.json`, call `run(**args)`, write `output.json`."

---

## 4. Module map (mirrors PRD §9.1)

```
src/proteinclaw/
  cli.py                        # Layer 5
  agent/
    core.py                     # Layer 4 — Claude Agent SDK loop
    skills.py                   # loads proteindesign.md → system prompt
    campaign.py                 # orchestrates RFD3→MPNN→ESM→AF2 per round
  sandbox/
    exec.py                     # RestrictedPython config + sandbox_exec tool
  tools/
    __init__.py                 # Tool dataclass + ToolRegistry + @register
    _container_tools.py         # auto-discovery of tool.yaml dirs
    _gpu_metrics.py             # shared VRAM monitor thread
    rfdiffusion3/               # 4-file GPU tool
    proteinmpnn/                # 4-file GPU tool
    esmfold/                    # 4-file GPU tool
    alphafold2_multimer/        # 4-file GPU tool
    uniprot.py                  # plain-Python tool
    pdb.py                      # plain-Python tool
    rcsb.py                     # plain-Python tool
    literature.py               # plain-Python tool
    web.py                      # plain-Python tool
  runner/
    router.py                   # ComputeRouter (GPU detect + VRAM check)
    local.py                    # LocalRunner (Docker dispatch)
  skills/
    proteindesign.md            # agent's domain knowledge (system-prompt)
  db.py                         # SQLite schema + CRUD
  report.py                     # report.html generator
```

The directory layout *is* the architecture. Adding a new model = creating one directory under `tools/<name>/` with four files (PRD §9.8). No edits to registry, router, runner, or agent.

---

## 5. Key abstractions

### 5.1 `Tool` (dataclass)

The agent's atomic unit of capability. One per registered function. Carries:

- Identity: `name` (`<category>.<tool>`), `display_name`, `description`, `category`, `usage_guide`.
- Contract: `parameters` (JSON Schema), `function` (callable returning the result envelope).
- Compute hints: `requires_gpu`, `min_vram_gb`, `gpu_profile`, `docker_image`, `timeout_s`.

`Tool` is read-only after registration. The registry holds the singletons; the router consults the compute hints to decide where to run.

### 5.2 Result envelope (uniform across all tools)

```python
# Success
{
  "summary": str,            # one-line human description (required)
  "metrics": dict,           # vram/time (required for GPU tools)
  "session_id": str,         # required if the tool writes artifacts
  # ...tool-specific fields (paths, sequences, scores, confidence, ...)
}

# Error
{
  "summary": "Error: <reason>",
  "error": "<short code or traceback>",
  "metrics": dict,           # if partial execution occurred
}
```

Every tool returns this shape. **Nothing raises out of `run()`** — errors are dicts. This is the contract that lets the agent loop never crash on a tool failure (PRD §9.7).

### 5.3 `session_id` and the per-session workspace

A `session_id` (UUID4 hex) is minted per `proteinclaw run`. The host runner creates `~/.proteinclaw/gpu-workspace/<session_id>/`, mounted into every container at `/workspace`. Tools write artifacts to `/workspace/<tool>_<step>/` and return **paths**. This is the breadcrumb that lets tool A's output become tool B's input without round-tripping multi-MB PDB strings through the LLM context window (PRD §9.3).

`session_id` is passed as `SESSION_ID` env var into containers; `implementation.py` reads it and writes outputs to the agreed path layout.

### 5.4 The 4-file tool convention

Every GPU model tool is exactly four files in its own directory:

| File | Role |
|---|---|
| `tool.yaml` | Schema + compute requirements + agent-facing description. Single source of truth. |
| `Dockerfile` | Pinned env, clones upstream repo, copies entrypoint + implementation. |
| `tool_entrypoint.py` | Universal shim (identical across tools) — JSON in → `run()` → JSON out. |
| `implementation.py` | The actual model wrapper. One function: `run(**kwargs) -> dict`. |

The shim is identical on purpose: the only contract between host and container is **JSON in via `/workspace/input.json`, JSON out via `/workspace/output.json`** (PRD §9.2).

### 5.5 `ToolRegistry` and auto-discovery

- Plain-Python tools register themselves with `@registry.register(...)` at import time.
- GPU tools are discovered by `tools/_container_tools.py` walking `tools/*/tool.yaml` at startup. The registered "function" is a placeholder that the router intercepts; it must never execute directly.

Adding a new model is purely additive: drop a directory, restart Python, the registry sees it.

### 5.6 `ComputeRouter`

`route(tool, **kwargs) -> dict`:

- `not requires_gpu` → call `tool.function(**kwargs)` in-process.
- `requires_gpu` → detect local GPU (`nvidia-smi`, cached for session) → compare VRAM against `min_vram_gb` → dispatch to `LocalRunner` or return `{"error": "compute_unavailable"}`.

**Local-only in v1.** No cloud routing, no SLURM. The router exists to give us a clean place to add those later without touching the agent.

### 5.7 `LocalRunner`

`run(tool, **kwargs) -> dict`:

1. Generate / accept `session_id`; ensure `~/.proteinclaw/gpu-workspace/<session_id>/` exists.
2. Write `input.json` with kwargs.
3. `docker images`; if missing, `docker build` from the tool's directory.
4. `docker run --gpus all` with:
   - `-v <workspace>:/workspace`
   - `-v ~/.cache/huggingface:/root/.cache/huggingface`
   - `-v ~/.cache/rfdiffusion:/root/.cache/rfdiffusion`
   - `-v ~/.cache/proteinmpnn:/root/.cache/proteinmpnn`
   - `-v ~/.cache/openfold:/root/.cache/openfold`
   - `-e INPUT_FILE=/workspace/input.json -e OUTPUT_FILE=/workspace/output.json -e SESSION_ID=<id>`
5. Enforce `tool.timeout_s`.
6. Read `output.json`; on container failure, return a structured error.

The runner is the **only** place that knows about Docker. Tools never see the runtime.

---

## 6. The narrow seams (do not widen)

These interfaces are what make the system extensible without rewrites. They are intentionally tiny.

| Seam | Interface |
|---|---|
| Agent ↔ Tools | `registry.get_tool(name)` + `router.route(tool, **kwargs)` |
| Host ↔ Container | JSON files in `/workspace`, `SESSION_ID` env var |
| Tool ↔ Tool | Workspace files (paths in result envelope); never direct imports |
| Skill ↔ Agent | `proteindesign.md` concatenated into system prompt at run start |
| User ↔ Agent | One natural-language prompt + optional flags; one allowed mid-run clarifying question for target resolution |

Anything tempted to widen one of these is almost always papering over a leaky abstraction — fix the abstraction (CLAUDE.md "Public seams stay narrow").

---

## 7. Control flow — one campaign end to end

```
proteinclaw run "design a binder to PD-L1's IgV domain"
        │
        ▼
 cli.py: validate doctor marker → mint session_id → build run dir
        │
        ▼
 agent/core.py: load proteindesign.md + tool descriptions → system prompt
        │
        ▼
 Claude Agent SDK loop ──┐
                ├── Step: literature_search("PD-L1 binders") [plain-Python tool]
                ├── Step: rcsb_search("PD-L1 IgV")          [plain-Python tool]
                │       └─ ambiguous? → ONE clarifying question to user
                ├── Step: pdb_fetch(5JDS, chain=A, crop=54-150)
                ├── Step: rfdiffusion3(target_pdb, hotspots, length)
                │         └─► ComputeRouter → LocalRunner → Docker
                │             └─► writes backbones to /workspace/rfd_1/
                │             └─► returns {designs: [<paths>], ...}
                ├── Step: proteinmpnn(backbones=<paths>, num_sequences=8)
                │         └─► writes FASTAs to /workspace/mpnn_2/
                ├── Step: esmfold(sequences=[...])  ← PRE-FILTER
                │         └─► agent picks discard threshold from pLDDT distribution
                ├── Step: alphafold2_multimer(binder_seq, target_seq)  ← RANKING
                │         └─► writes complex PDBs; returns binder-chain pLDDT
                │
                ├── (if --rounds > 1) agent reflects → narrow params → loop
                │
                └── Triage: top-K by AF2 complex pLDDT → write outputs
        │
        ▼
 db.py: insert run + designs + agent_steps rows
        │
        ▼
 report.py: render report.html (rank table, ESM vs AF2 scatter, 3D viewer)
```

Every step appends a row to `trace.jsonl`. The trace, not a seed, is the reproducibility artifact (PRD §7).

---

## 8. Data flow — what crosses what boundary

| What | Where it lives | How it crosses boundaries |
|---|---|---|
| User prompt | CLI argv | Passed to agent as first user turn |
| Skill knowledge | `skills/proteindesign.md` | Concatenated into system prompt at agent init |
| Tool descriptions | `tool.yaml` per tool | Registry assembles, agent reads in system prompt |
| Tool args | LLM-generated JSON | Validated against `tool.parameters` JSON Schema by registry |
| Tool inputs (large) | `/workspace/input.json` + workspace files | Mounted into container; never in JSON envelope |
| Tool outputs (large) | `/workspace/<tool>_<step>/*` | Returned as **paths** in JSON envelope |
| Tool result summary | JSON envelope | Read by agent; small `metrics` block; *no PDB bytes* |
| Run metadata | SQLite | Written at start/end; read by `history` / `show` |
| Trace | `runs/<run_id>/trace.jsonl` | Appended on every agent step + tool call |
| Weights | `~/.cache/{hf,rfdiffusion,proteinmpnn,openfold}` | Bind-mounted into every container; lazy download on first miss |

**The cardinal rule: PDB bytes never cross the LLM context window.** Paths cross. The agent reads files only when it needs to (via `sandbox_exec`).

---

## 9. Security model

### 9.1 The sandbox boundary

The Claude agent itself runs via the Claude Agent SDK (separate process, sandboxed by the SDK's own permission model). Any host-side glue code we want to execute outside that boundary (e.g., `sandbox_exec` for one-off parsing) runs inside **RestrictedPython** with an allowlist:

- **Allowed:** `json`, `re`, `math`, `os.path`, `pathlib` (read-only ops), `collections`, `Bio` (Biopython), `numpy`, plus the registered tool functions injected by name.
- **Blocked:** writes outside the run's `output-dir`, raw `subprocess`/`os.system`, network calls except through registered tools, `eval`/`exec` on non-sandboxed code, imports outside the allowlist.

### 9.2 The container boundary

GPU models do **not** run in the sandbox. The sandbox calls a tool function which dispatches through `ComputeRouter` → `LocalRunner` → `docker run --gpus all`. Inside the container, the model has full root and full GPU but is isolated from the host filesystem except for:

- `/workspace` (this session only)
- The four weight cache mounts

Containers are torn down after each invocation.

### 9.3 Trust boundaries

| Boundary | Trust |
|---|---|
| User prompt → Agent | **Untrusted** — agent must validate before acting on naming, structure, etc. |
| Agent → Tool args | **Untrusted** — registry enforces JSON Schema validation per tool |
| Tool result envelope → Agent | **Trusted** (tool is in-tree code) but agent should never act on absent metrics |
| External APIs (RCSB, UniProt, Semantic Scholar, ColabFold, DuckDuckGo) | **Untrusted** — handle 4xx/5xx/timeouts; degrade gracefully where the PRD allows |
| Docker daemon | **Trusted** (the user installed it) |
| Weights downloaded lazily | Magic-byte sanity check before reuse (PRD §9.9 RFdiffusion3 notes) |

### 9.4 Secrets

- Claude authentication: two supported paths. (a) **Subscription (default)**: `claude login` writes OAuth credentials to `~/.claude/.credentials.json` and the Agent SDK picks them up automatically — billing flows against the Pro/Max subscription credit pool. ANTHROPIC_API_KEY must NOT be set, since the SDK silently prefers the API key when both are present. (b) **API path**: `ANTHROPIC_API_KEY` set in env — pay-as-you-go, useful for CI / shared automation. `doctor` reports which path is active and warns when both are set. Neither credential is logged.
- No other credentials in v1. All external APIs are keyless (Semantic Scholar low-volume, UniProt, RCSB, DuckDuckGo HTML).

---

## 10. Failure model

### 10.1 Fail-fast principles

- **No silent fallbacks to degraded pipelines.** If RCSB target resolution fails → run fails with a clear error. No AlphaFold DB fallback in v1.
- **All errors return a dict, never raise.** `run()` catches and converts. The agent reads the dict and decides what to do.
- **`proteinclaw doctor` must pass** before `proteinclaw run` is allowed. The CLI enforces this via a marker file.

### 10.2 The three deliberate graceful-degradation paths

These are the only places we intentionally swallow a failure rather than failing the run:

1. **Literature search rate-limited** (Semantic Scholar) → return `{summary: "rate-limited", results: []}`; agent proceeds without literature input.
2. **DuckDuckGo scrape failure** → return `{summary: "web search unavailable", results: []}`; agent proceeds.
3. **ColabFold MSA timeout** (AF2-multimer) → retry once, then fall back to single-sequence MSA for that chain, **log the degradation loudly** so the agent knows the prediction is weaker.

Anything else that fails → fails the run with the error envelope.

### 10.3 What the agent owns vs what the system owns

| Owner | Failures it handles |
|---|---|
| System (runner/router) | GPU below floor, Docker missing, container nonzero exit, timeout, malformed `tool.yaml` |
| Agent (via skill file) | Tool returned `error` envelope → retry with adjusted params, or give up and explain |
| User | `doctor` failures (install Docker, free disk, etc.) |

---

## 11. The ranking signal (why the cascade matters)

The cascade exists for one reason: **AF2-multimer on the complex is expensive, ESMFold on the monomer is cheap**. ESMFold filters out designs that don't even fold in isolation; AF2-multimer then ranks the survivors by how well they fold *with the target*.

| Metric | Source | Role |
|---|---|---|
| `confidence` (monomer pLDDT 0–100) | ESMFold | Pre-filter only. Agent picks the discard threshold per round and logs it. |
| `complex_confidence` (binder-chain pLDDT 0–100) | AF2-multimer | **The ranking signal.** Top-K by this value. |

A design with high monomer pLDDT but low complex pLDDT folds fine but doesn't dock — the report surfaces both so users can see this. Ranking by monomer pLDDT alone (the naive thing) would promote non-binders. **This is the entire reason for the cascade.**

Interface metrics (iPAE, ddG, SC/SASA) are deferred to v2+.

---

## 12. Persistence layout

```
~/.proteinclaw/
  config.toml                          # optional model selection (no auth — OAuth in ~/.claude/)
  doctor_ok                            # marker; gates `run`
  runs.db                              # SQLite (runs, designs, agent_steps)
  gpu-workspace/<session_id>/          # per-session container mount
    input.json / output.json
    rfdiffusion3_1/*.pdb
    proteinmpnn_2/*.fa
    esmfold_3/*.pdb
    alphafold2_multimer_4/*.pdb

<output-dir>/<run_id>/                 # the user-facing artifacts
  designs/rank_NN_<id>.{pdb,fasta}
  report.html
  plan.md
  trace.jsonl
  literature.md
  config/
  raw/

~/.cache/
  huggingface/                         # ESMFold weights
  rfdiffusion/                         # RFD3 weights
  proteinmpnn/                         # MPNN weights
  openfold/                            # AF2 params + alignments
```

The session workspace is per-run scratch; the output dir is what the user keeps; `~/.cache/*` is shared across runs and across `proteinclaw` versions.

SQLite schema (minimum, PRD §6.9):

- `runs(run_id, session_id, prompt, target_pdb_id, target_chain, target_crop, started_at, ended_at, status, num_designs, output_dir, agent_model, git_sha)`
- `designs(design_id, run_id, rank, plddt_esm_monomer, plddt_af2_complex, pdb_path, fasta_path)`
- `agent_steps(step_id, run_id, step_idx, role, content, tool, tool_args, tool_result_summary, timestamp)`

**Top pLDDT is not denormalized.** Derive from `designs.plddt_af2_complex` when needed (PRD §6.9).

---

## 13. Extensibility: how the architecture changes when you add things

| Change | What you edit |
|---|---|
| **Add a new GPU model** | Create `tools/<name>/{tool.yaml, Dockerfile, implementation.py, tool_entrypoint.py}`. Restart Python. Done. |
| **Add a new plain-Python tool** | Create `tools/<name>.py` with `@registry.register(...)`. Done. |
| **Change agent behavior** (e.g. new recipe, new threshold heuristic) | Edit `skills/proteindesign.md`. No code change. |
| **Change ranking signal** | Edit `agent/campaign.py` triage block + report. Document in PRD. |
| **Add cloud / SLURM dispatch** | Add a new runner under `runner/`; teach `ComputeRouter.route()` to choose it. Tools unchanged. |
| **Add a new output format** | Edit `report.py`. Tools/agent unchanged. |
| **Add a new metric** (e.g. iPAE) | Extend `designs` table; teach the AF2 tool to return it; teach report to render it; teach agent to consider it. Bigger change — coordinate. |

The architecture's core promise: **adding a model is one directory, no other edits**. If you find yourself editing the registry, router, or agent to add a model, something is wrong with the design.

---

## 14. What this architecture explicitly is *not*

Per PRD §3 (non-goals) and §13 (deferred to v2+):

- Not a multi-node orchestrator. Single local GPU node only.
- Not a cloud product. `ComputeRouter` is local-only in v1.
- Not self-iterating beyond the user's `--rounds` budget.
- Not a wet-lab pipeline. No DNA / protocol output.
- Not a multi-modality system. Natural language is the **only** input in v1.
- Not a fallback-rich system. Fail fast, fail loud, except for the three documented degradation paths (§10.2).

When in doubt, prefer the simpler architecture and defer.

---

## 15. Glossary of seams (one-liners)

- **Tool result envelope** — uniform dict shape; the only thing tools return.
- **Session workspace** — per-run host dir mounted into every container at `/workspace`.
- **Skill file** — `proteindesign.md`, concatenated into system prompt at every run start.
- **4-file convention** — every GPU tool is `tool.yaml` + `Dockerfile` + `implementation.py` + (universal) `tool_entrypoint.py`.
- **Cascade** — ESMFold (cheap, monomer, filter) → AF2-multimer (expensive, complex, rank).
- **Complex pLDDT** — average pLDDT over the binder chain in the AF2-multimer prediction. The ranking signal.
- **Trace** — `trace.jsonl`; the reproducibility artifact (not a seed).

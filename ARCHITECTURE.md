# ARCHITECTURE.md — `proteinclaw`

**Status:** v1.0.0
**Scope:** How the pieces fit together, why they're shaped that way, and where the seams are.
**Read first:** `PRD-proteinclaw.md` §9 (Implementation) is normative; this document explains and connects it. When this doc and the PRD disagree, the PRD wins. For cross-session footguns and corrections, see `NOTES.md`.

---

## 1. One-paragraph overview

`proteinclaw` is a Python CLI that turns a natural-language binder-design prompt into a ranked set of binder candidates. A Claude-backed agent (via the **Claude Agent SDK**, billed against the user's Claude Pro/Max subscription credit pool) drives the campaign through an in-process MCP server that wraps our tool registry, dispatching GPU-heavy model calls (RFdiffusion3, ProteinMPNN, ESMFold, AlphaFold2-multimer) out to **local Docker containers** via a `ComputeRouter` → `LocalRunner` chain. Tools share state through a per-run **session workspace** mounted into every container; they pass *paths*, never multi-MB PDB bytes, through the LLM context. Designs are ranked by **AF2-multimer complex pLDDT averaged over the binder chain**; ESMFold is only a fast monomer pre-filter the agent uses to discard non-folders before the expensive AF2 step. A suite of **interface-quality metrics** (ipSAE / ipTM / pDockQ / LIS + deterministic biopython interface QC) is computed per design and feeds a strict multi-metric "hit" gate the agent uses to decide when to stop.

---

## 2. Layered view

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 4: CLI                              proteinclaw run / setup /   │
│                                           doctor / history / show /   │
│                                           cancel / skills             │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 3: Agent Core                       Claude Agent SDK loop +     │
│                                           skill loader + in-process   │
│                                           MCP server + research scout │
│                                           subagents + trace writer +  │
│                                           triage + report             │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 2: Tool Registry + Router           registry  →  ComputeRouter  │
│                                                       →  LocalRunner   │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 1: Tools                                                        │
│   Plain-Python (in-process):  uniprot, pdb, rcsb, literature,         │
│                               pubmed, interface_metrics               │
│   GPU (Docker):  rfdiffusion3, proteinmpnn, esmfold, af2_multimer     │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 0: Persistence                      SQLite (~/.proteinclaw/     │
│                                           runs.db) + session          │
│                                           workspace + weight caches    │
└──────────────────────────────────────────────────────────────────────┘
```

Arrows in this stack point downward only. The agent never reaches past the registry to a tool's internals; the runner never reaches up to the agent. Each seam is narrow on purpose (§6).

There is **no separate RestrictedPython sandbox layer.** The PRD's original `sandbox_exec` tool was not built — the agent's non-tool glue code runs through the Claude Agent SDK's own built-in `Bash`, scoped to a per-run `./scratch/` directory (§9.1).

---

## 3. Process / container topology

```
HOST process (proteinclaw CLI)
├── Python runtime
│   ├── Claude Agent SDK loop (`claude_agent_sdk.query` / `ClaudeSDKClient`)
│   │   ├── in-process MCP server  (wraps registry.route via @tool)
│   │   ├── SDK built-ins: Bash (scoped to ./scratch/), Read, Write, Edit,
│   │   │                  WebFetch, WebSearch, Agent (spawns scouts)
│   │   └── read-only research scout subagents (Sonnet / Opus)
│   ├── plain-Python tools run HERE (in-process)
│   ├── GPU tools dispatch  → ComputeRouter → LocalRunner → Docker
│   ├── SQLite writer  (~/.proteinclaw/runs.db)
│   └── trace.jsonl appender
│
└── Docker (one container per GPU tool invocation)
    ├── /workspace  ← bind-mounted from
    │                  ~/.proteinclaw/gpu-workspace/<session_id>/
    ├── /cache/{huggingface,rfdiffusion,proteinmpnn,openfold}
    │                ← bind-mounted from host ~/.cache/*
    ├── tool_entrypoint.py  (universal shim, identical per tool)
    └── implementation.py   (the actual model wrapper)
```

The host is the only long-lived process. Each GPU container is **single-purpose, single-use**: spun up for one `run()` call and torn down. The container has no knowledge of the agent, the registry, or other tools — it only knows "read `input.json`, call `run(**args)`, write `output.json`."

> **Mount path note:** weight caches mount at `/cache/<name>`, *not* `/root/.cache/<name>`. Containers run as the host UID/GID (`docker run -u $(id -u):$(id -g)`) so workspace artifacts aren't root-owned, and that UID can't write under `/root`. Each tool's Dockerfile sets the matching env var (`HF_HOME=/cache/huggingface`, etc.). See `NOTES.md` → "Shared LocalRunner mechanics".

---

## 4. Module map (mirrors PRD §9.1)

```
src/proteinclaw/
  cli.py                        # Layer 4 — Typer CLI (run/setup/doctor/history/show/cancel/skills)
  setup.py                      # `proteinclaw setup` guided first-run walk-through
  doctor.py                     # GPU / Docker / weights / deps / auth preflight checks
  agent/
    core.py                     # Layer 3 — Claude Agent SDK loop, option assembly, scout defs
    skills.py                   # load_skill_text(): core skill + tool-skill index → system prompt
    mcp_tools.py                # in-process MCP server wrapping registry.route() via @tool
    trace.py                    # TraceWriter — append-only trace.jsonl
    triage.py                   # parse_trace + rank + interface-metric annotation + stage outputs
  tools/
    __init__.py                 # Tool dataclass + ToolRegistry + @register
    _container_tools.py         # auto-discovery of tool.yaml dirs
    _gpu_metrics.py             # shared VRAM-monitor thread (copied into each GPU image)
    _http.py                    # shared UA + timeout HTTP helper
    _paths.py                   # session workspace + per-host cache helpers
    rfdiffusion3/               # 4-file GPU tool (+ _normalize.py)
    proteinmpnn/                # 4-file GPU tool (+ _normalize.py)
    esmfold/                    # 4-file GPU tool (+ _normalize.py)
    alphafold2_multimer/        # 4-file GPU tool (+ _normalize.py)
    _smoke/                     # trivial 4-file GPU tool (proves the dispatch path)
    uniprot.py                  # plain-Python tool
    pdb.py                      # plain-Python tool
    rcsb.py                     # plain-Python tool
    literature.py               # plain-Python tool (LitSense)
    pubmed.py                   # plain-Python tool (NCBI E-utilities)
    interface_metrics.py        # plain-Python tool — analysis.interface_metrics (in-process biopython)
  analysis.py                   # pure compute_interface_metrics(); shared by the tool + triage
  runner/
    router.py                   # ComputeRouter (GPU detect + VRAM check)
    local.py                    # LocalRunner (Docker dispatch)
  skills/
    proteindesign.md            # CORE skill — concatenated into the system prompt every run
    tools/<tool>.md             # per-tool detail — Read on demand (progressive disclosure)
    learned/<topic>.md          # agent's self-evolved lessons — auto-indexed next run
  db.py                         # SQLite schema (migrated idempotently) + CRUD
  report.py                     # report.html generator (tabs, metric suite, hit gate)
```

The directory layout *is* the architecture. Adding a new model = creating one directory under `tools/<name>/` with four files (PRD §9.2). No edits to registry, router, runner, or agent.

> Each GPU tool dir also carries a fifth helper, `_normalize.py` (parameter/PDB normalisation extracted so host-side unit tests can import it without the container-only imports in `implementation.py`). This is an allowed, deliberate exception to "four files" — see `NOTES.md`.

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

`session_id` is passed as the `SESSION_ID` env var into containers; `implementation.py` reads it and writes outputs to the agreed path layout. On return, `LocalRunner._translate_workspace_paths` rewrites `/workspace/...` paths in the envelope back to host paths so the host can read them.

> **Path footgun:** paths handed *across* tools must stay in the `/workspace/...` form the next container will see — GPU tools reject a translated host path (`target_pdb must live under /workspace/`). See `NOTES.md`.

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

### 5.6 In-process MCP server

`agent/mcp_tools.py` wraps every registered tool as a `@tool`-decorated function on an in-process MCP server (`create_sdk_mcp_server`). Each wrapper injects the run's `session_id`, calls `registry.route(tool, **kwargs)`, and returns the result envelope as the tool result. This is the only bridge between the SDK's tool-calling loop and our registry — the agent sees MCP tools named `mcp__proteinclaw__<category>_<tool>`, never our Python functions directly.

### 5.7 `ComputeRouter`

`route(tool, **kwargs) -> dict`:

- `not requires_gpu` → call `tool.function(**kwargs)` in-process.
- `requires_gpu` → detect local GPU (`nvidia-smi`, cached for session) → compare VRAM against `min_vram_gb` → dispatch to `LocalRunner` or return `{"error": "compute_unavailable"}`.

**Local-only in v1.** No cloud routing, no SLURM. The router exists to give us a clean place to add those later without touching the agent.

### 5.8 `LocalRunner`

`run(tool, **kwargs) -> dict`:

1. Generate / accept `session_id`; ensure `~/.proteinclaw/gpu-workspace/<session_id>/` exists.
2. Write `input.json` with kwargs.
3. `docker images`; if missing, build from the tool's directory (staging the tool dir + shared helpers like `_gpu_metrics.py` into a tempdir so the Dockerfile can `COPY` them).
4. `docker run --gpus all -u $(id -u):$(id -g)` with:
   - `-v <workspace>:/workspace`
   - `-v ~/.cache/huggingface:/cache/huggingface` (and `rfdiffusion`, `proteinmpnn`, `openfold`)
   - `-e INPUT_FILE=/workspace/input.json -e OUTPUT_FILE=/workspace/output.json -e SESSION_ID=<id>`
   - `--label proteinclaw.session=<sid>` (so `proteinclaw cancel` can find and kill it)
5. Enforce `tool.timeout_s`.
6. Read `output.json`; translate `/workspace/...` paths → host paths; on container failure, return a structured error.

The runner is the **only** place that knows about Docker. Tools never see the runtime.

### 5.9 Research scouts + the debate mechanic

When `--research-fanout` is on (default), `core._research_agents()` defines two **read-only** subagents the main agent can spawn:

- `research` — **Sonnet**, the cheap default for fanned-out research.
- `research_pro` — **Opus**, the escalation tier used only to retry a scout that Sonnet's safety classifier refused.

Their `tools` allowlist physically bars GPU/Write/Bash — a scout can only `WebSearch`/`WebFetch` and run the read-only literature/pubmed tools, never run the pipeline or write deliverables. Scouts are stateless one-shots: the whole debate state (PROPOSE a sub-topic, or DEFEND a challenge) lives in the spawn prompt. The skill drives a **propose → challenge → adjudicate → converge** debate whose substance the agent records in `plan.md`.

> **Hotspots are determined by the main agent's own structural sandbox**, not by scouts. Sonnet's classifier refuses immune-checkpoint *interface/residue* queries at the topic level (rephrasing does not help), so the robust design is **routing, not fighting the filter**: the agent computes contacts/BSA on the co-crystal PDB via its `Bash` scratch (biopython Shrake-Rupley + NeighborSearch — `freesasa` lives only in the GPU containers, not the host venv), and points scouts only at filter-safe topics (prior campaigns, fold designability, length/topology, developability). See `NOTES.md` → "Research fan-out + the scout-refusal finding".

### 5.10 Skills: lean core + progressive disclosure + self-evolution

`skills/proteindesign.md` is the **core** skill — concatenated into the agent's system prompt at the start of every run (not a tool result, not lazy-loaded). It carries the pipeline overview, cardinal rules, the research/debate/hypothesis workflow, hotspot strategy, the quality gate, triage, and the self-refining loop.

Per-tool operational detail lives in `skills/tools/<tool>.md` and is **progressively disclosed**: `skills.py:load_skill_text()` appends a **Tool skill index of absolute paths** (the agent's cwd is the run dir, so relative paths wouldn't resolve) and the agent `Read`s the relevant file before each tool step. Optional `skills/learned/*.md` are indexed the same way. `load_skill_text()` fails loud if the core file or the `tools/` dir is missing/empty.

**Self-evolution.** Optionally, at a round boundary, the agent may promote a durable, generalizable lesson from `plan.md` into the global skill files — appending to a `skills/tools/<tool>.md` or creating a `skills/learned/<topic>.md`. This is **append-only** (`## Learned (run <id>, <date>)` blocks; corrections are additive, never rewrites), which preserves the content-lock invariant tests (`test_skill_invariants.py`, run via `proteinclaw skills check`) as a loud safety net. `core.py` grants the skills dir via the SDK's `add_dirs`; edits land in git-tracked `src/proteinclaw/skills/`, so they show in `git status`, ship in the wheel, and take effect on the *next* run. Review/revert with `proteinclaw skills diff|log|reset`; a human commits good edits. **Source/editable install only** — a wheel install has no writable tracked source. Run summaries + `result.json` list any skills evolved that round.

---

## 6. The narrow seams (do not widen)

These interfaces are what make the system extensible without rewrites. They are intentionally tiny.

| Seam | Interface |
|---|---|
| Agent ↔ Tools | in-process MCP `@tool` → `registry.get_tool(name)` + `router.route(tool, **kwargs)` |
| Host ↔ Container | JSON files in `/workspace`, `SESSION_ID` env var |
| Tool ↔ Tool | Workspace files (paths in result envelope); never direct imports |
| Skill ↔ Agent | `proteindesign.md` concatenated into system prompt at run start; tool skills Read on demand |
| Agent ↔ Scouts | spawn prompt in, research findings out; scouts are read-only and stateless |
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
 agent/core.py: load proteindesign.md + tool-skill index → system prompt;
                assemble ClaudeAgentOptions (MCP server, built-ins, scouts)
        │
        ▼
 Claude Agent SDK loop ──┐
                ├── Research/debate: spawn read-only scouts (prior campaigns,
                │       designability, developability) → record in plan.md
                ├── Step: rcsb_search / pdb_fetch (resolve target structure)
                │       └─ ambiguous? → ONE clarifying question to user
                ├── Step: Bash scratch — contacts/BSA on the co-crystal → hotspots
                ├── Step: rfdiffusion3(target_pdb, hotspots, length)
                │         └─► ComputeRouter → LocalRunner → Docker
                │             └─► writes backbones to /workspace/rfdiffusion3_1/
                ├── Step: proteinmpnn(backbones=<paths>, num_sequences=N)
                ├── Step: esmfold(sequences=[...])  ← PRE-FILTER
                │         └─► agent picks discard threshold from pLDDT distribution
                ├── Step: alphafold2_multimer(binder_seq, target_seq)  ← RANKING
                │         └─► writes complex PDBs; returns binder-chain pLDDT + ipSAE
                │
                ├── (if --rounds > 1) agent reflects vs the strict hit gate →
                │       narrow params → loop; may self-evolve a skill
                │
                └── Triage: rank by AF2 complex pLDDT, annotate interface metrics,
                            stage top-K designs → write outputs
        │
        ▼
 db.py: insert run + designs + agent_steps rows
        │
        ▼
 report.py: render report.html (rank table + interface metrics, hit gate,
            ESM-vs-AF2 scatter, 3D viewer, plan & debate, raw-trace tab)
```

Every step appends a row to `trace.jsonl`. The trace, not a seed, is the reproducibility artifact (PRD §7).

---

## 8. Data flow — what crosses what boundary

| What | Where it lives | How it crosses boundaries |
|---|---|---|
| User prompt | CLI argv | Passed to agent as first user turn |
| Skill knowledge | `skills/proteindesign.md` (+ tool skills) | Core concatenated into system prompt; tool skills Read on demand |
| Tool descriptions | `tool.yaml` per tool | Registry assembles, exposed via MCP tool schemas |
| Tool args | LLM-generated JSON | Validated against `tool.parameters` JSON Schema by registry |
| Tool inputs (large) | `/workspace/input.json` + workspace files | Mounted into container; never in JSON envelope |
| Tool outputs (large) | `/workspace/<tool>_<step>/*` | Returned as **paths** in JSON envelope |
| Tool result summary | JSON envelope | Read by agent; small `metrics` block; *no PDB bytes* |
| Agent reasoning / debate | `runs/<run_id>/plan.md` | Written by the agent; inlined into report.html |
| Run metadata | SQLite | Written at start/end; read by `history` / `show` |
| Trace | `runs/<run_id>/trace.jsonl` | Appended on every agent step + tool call |
| Weights | `~/.cache/{huggingface,rfdiffusion,proteinmpnn,openfold}` | Bind-mounted into every container at `/cache/*`; lazy download on first miss |

**The cardinal rule: PDB bytes never cross the LLM context window.** Paths cross. The agent reads files only when it needs to (via its `Bash`/`Read` scratch tools).

---

## 9. Security model

### 9.1 The agent's execution boundary

The Claude agent runs via the Claude Agent SDK with `permission_mode="bypassPermissions"` (autonomous runs can't stop to prompt per tool call). Its outbound surface is therefore the registered MCP tool set **plus** the SDK's own built-ins: `Bash`, `Read`, `Write`, `Edit`, `WebFetch`, `WebSearch`, and `Agent` (scout spawn). Glue code (PDB parsing, contact/BSA calculation, scratch Python) runs through that built-in `Bash`, scoped to a per-run `./scratch/` directory — **not** a RestrictedPython sandbox (the PRD's `sandbox_exec` was never built; `RestrictedPython` remains a dependency but is unused in the live path).

Practical consequence: the agent's `Bash` runs in the **host venv**, where `freesasa` is *not* installed (it lives only inside the GPU containers). The structural sandbox therefore uses biopython's Shrake-Rupley + `NeighborSearch`, and the skill says so explicitly.

### 9.2 The container boundary

GPU models do **not** run in-process. The MCP wrapper calls a tool function which dispatches through `ComputeRouter` → `LocalRunner` → `docker run --gpus all`. Inside the container, the model has full GPU access but is isolated from the host filesystem except for:

- `/workspace` (this session only)
- The four weight cache mounts (`/cache/*`)

Containers run as the host UID/GID and are torn down after each invocation.

### 9.3 Trust boundaries

| Boundary | Trust |
|---|---|
| User prompt → Agent | **Untrusted** — agent must validate before acting on naming, structure, etc. |
| Agent → Tool args | **Untrusted** — registry enforces JSON Schema validation per tool |
| Tool result envelope → Agent | **Trusted** (tool is in-tree code) but agent should never act on absent metrics |
| External APIs (RCSB, UniProt, LitSense, PubMed/NCBI, ColabFold MSA server, SDK web search) | **Untrusted** — handle 4xx/5xx/timeouts; degrade gracefully where the PRD allows |
| Docker daemon | **Trusted** (the user installed it) |
| Weights downloaded lazily | Magic-byte sanity check before reuse (PRD §9.9 RFdiffusion3 notes) |

### 9.4 Secrets

- Claude authentication: two supported paths. **(a) Subscription (default):** `claude login` writes OAuth credentials to `~/.claude/.credentials.json` and the Agent SDK picks them up automatically — billing flows against the Pro/Max subscription credit pool. `ANTHROPIC_API_KEY` must **not** be set, since the SDK silently prefers the API key when both are present (a real footgun — `doctor.check_claude_auth` is 4-state and warns loudly). **(b) API path:** `ANTHROPIC_API_KEY` set in env — pay-as-you-go, useful for CI / shared automation. Neither credential is logged.
- `~/.proteinclaw/config.toml` holds model selection only — no secrets.
- No other credentials in v1. All external research/data APIs are keyless (UniProt, RCSB, LitSense, PubMed E-utilities, ColabFold).

---

## 10. Failure model

### 10.1 Fail-fast principles

- **No silent fallbacks to degraded pipelines.** If RCSB target resolution fails → run fails with a clear error. No AlphaFold DB fallback in v1.
- **All errors return a dict, never raise.** `run()` catches and converts. The agent reads the dict and decides what to do.
- **`proteinclaw doctor` must pass** before `proteinclaw run` is allowed. The CLI enforces this via a marker file (`~/.proteinclaw/doctor_ok`; bypass with `--skip-doctor`, dev/test only).

### 10.2 The deliberate graceful-degradation paths

These are the only places we intentionally swallow a failure rather than failing the run, and they all log loudly:

1. **Literature / PubMed rate-limited** → return `{rate_limited: true, results: []}`; agent proceeds without that input. (A 429 is correct degradation, not a tool bug — PRD §10.2.)
2. **SDK web search unavailable** (WebFetch/WebSearch error) → agent proceeds on the structural + literature evidence it has.
3. **ColabFold MSA timeout** (AF2-multimer) → retry once, then fall back to single-sequence MSA for that chain, logging the degradation so the agent knows the prediction is weaker.

Interface metric scorers (ipSAE etc.) also **soft-fail by design**: a scorer failure leaves the structure intact with `ipsae=null` + an error note; ranking still sorts by `complex_confidence`. Anything else that fails → fails the run with the error envelope.

### 10.3 Cancellation

`proteinclaw cancel` stops real work, not just a DB flag: `docker kill` containers by the `proteinclaw.session` label + SIGTERM the recorded `runs.pid` + mark the run `cancelled`. In-process Ctrl-C / `CancelledError` is caught by `core._drive` → status `cancelled`, with triage still run on partials. A background-task **timeout** that SIGKILLs the process bypasses this — the SQLite row can be left at `running` (re-parse the trace by hand). See `NOTES.md`.

### 10.4 What the agent owns vs what the system owns

| Owner | Failures it handles |
|---|---|
| System (runner/router) | GPU below floor, Docker missing, container nonzero exit, timeout, malformed `tool.yaml` |
| Agent (via skill file) | Tool returned `error` envelope → retry with adjusted params, or give up and explain |
| User | `doctor` failures (install Docker, free disk, etc.) |

---

## 11. The ranking signal + interface metrics (why the cascade matters)

The cascade exists for one reason: **AF2-multimer on the complex is expensive, ESMFold on the monomer is cheap**. ESMFold filters out designs that don't even fold in isolation; AF2-multimer then ranks the survivors by how well they fold *with the target*.

| Metric | Source | Role |
|---|---|---|
| `confidence` (monomer pLDDT 0–100) | ESMFold | Pre-filter only. Agent picks the discard threshold per round and logs it. |
| `complex_confidence` (binder-chain pLDDT 0–100) | AF2-multimer | **The ranking signal.** Top-K by this value. The triage sort never changed. |
| `ipsae` / `iptm` / `pdockq` / `pdockq2` / `lis` | Dunbrack `ipsae.py` over the rank-1 PAE | Interface confidence — advisory + feed the hit gate. |
| `hotspot_satisfaction`, `interface_bsa`, `n_interface_contacts`, `clash_score` | `analysis.compute_interface_metrics` (biopython) | Deterministic interface QC over the AF2 complex PDB. |

A design with high monomer pLDDT but low complex pLDDT folds fine but doesn't dock — the report surfaces both so users can see this. Ranking by monomer pLDDT alone (the naive thing) would promote non-binders. **This is the entire reason for the cascade.**

**Strict multi-metric hit gate.** A design is a "hit" only if it clears *all* of: complex pLDDT > 85 **and** `ipsae` ≥ 0.6 **and** `iptm` ≥ 0.7 **and** hotspot satisfaction ≥ 0.70 **and** BSA ≳ 700 Å². A missing metric **fails** the gate. The gate governs *when the agent stops* (gate met ≈ ≥3 hits), not the sort order. The thresholds live in three places that must stay in sync: the skill's Quality-gate table, `tools/alphafold2_multimer.md`, and `report._GATE` / `_is_hit()`.

> **Scoping (deliberate):** KD (PRODIGY) was dropped — contact-based KD is untrustworthy from a predicted designed complex. Rosetta ddG (`ddG < −20 REU`, Bennett 2023) is the one literature-validated discriminator but is **deferred** to a follow-on PyRosetta CPU container (non-commercial license, ~1 min/complex). The shipped metrics are QC/confidence signals the agent weighs in its gate. See `NOTES.md` → "Deterministic interface metrics".

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
  report.html                          # tabs: Design report + Raw trace
  plan.md                              # agent's run notebook (reasoning, hypotheses, debate log)
  trace.jsonl
  literature.md
  config/
  raw/

~/.cache/                              # shared across runs; bind-mounted at /cache/* in containers
  huggingface/                         # ESMFold weights
  rfdiffusion/                         # RFD3 weights
  proteinmpnn/                         # MPNN weights
  openfold/                            # AF2 params + alignments
```

The session workspace is per-run scratch; the output dir is what the user keeps; `~/.cache/*` is shared across runs and across `proteinclaw` versions.

**SQLite schema** (PRD §6.9) is **migrated idempotently** via `PRAGMA table_info`-guarded `ALTER TABLE`. The current version is **4** (v1 base → v2 ipSAE columns → v3 `runs.pid` → v4 interface-QC columns). Tests assert against `db.CURRENT_SCHEMA_VERSION`, not a literal.

- `runs(run_id, session_id, prompt, target_pdb_id, target_chain, target_crop, started_at, ended_at, status, num_designs, output_dir, agent_model, git_sha, pid)`
- `designs(design_id, run_id, rank, plddt_esm_monomer, plddt_af2_complex, ipsae, iptm, pdockq, lis, hotspot_satisfaction, n_interface_contacts, interface_bsa, clash_score, pdockq2, ipsae_d0chn, pdb_path, fasta_path)`
- `agent_steps(step_id, run_id, step_idx, role, content, tool, tool_args, tool_result_summary, timestamp)`

**Top pLDDT is not denormalized.** Derive from `designs.plddt_af2_complex` when needed (PRD §6.9).

---

## 13. Extensibility: how the architecture changes when you add things

| Change | What you edit |
|---|---|
| **Add a new GPU model** | Create `tools/<name>/{tool.yaml, Dockerfile, implementation.py, tool_entrypoint.py}` (+ optional `_normalize.py`). Restart Python. Done. |
| **Add a new plain-Python tool** | Create `tools/<name>.py` with `@registry.register(...)`. Done. |
| **Change agent behavior** (new recipe, threshold heuristic, debate flow) | Edit `skills/proteindesign.md` or a `skills/tools/<tool>.md`. No code change. |
| **Change ranking / triage** | Edit `agent/triage.py` (sort + annotation) and `report.py`. Document in PRD. |
| **Change the hit gate** | Edit the skill's gate table, `tools/alphafold2_multimer.md`, and `report._GATE` together (keep all three in sync). |
| **Add cloud / SLURM dispatch** | Add a new runner under `runner/`; teach `ComputeRouter.route()` to choose it. Tools unchanged. |
| **Add a new output format** | Edit `report.py`. Tools/agent unchanged. |
| **Add a new metric** (e.g. Rosetta ddG) | Add the source (a CPU tool or AF2 envelope field) → bump the DB schema (`_*_ADDED_COLUMNS` + `CURRENT_SCHEMA_VERSION`) → teach `triage.py` + `report.py` to surface it → teach the skill to weigh it. Coordinated change. |

The architecture's core promise: **adding a model is one directory, no other edits**. If you find yourself editing the registry, router, or agent to add a model, something is wrong with the design.

---

## 14. What this architecture explicitly is *not*

Per PRD §3 (non-goals) and §13 (deferred to v2+):

- Not a multi-node orchestrator. Single local GPU node only.
- Not a cloud product. `ComputeRouter` is local-only in v1.
- Not self-iterating beyond the user's `--rounds` budget (the agent may self-pace under `--no-cap`, but within that budget).
- Not a wet-lab pipeline. No DNA / protocol output.
- Not a multi-modality system. Natural language is the **only** input in v1.
- Not a fallback-rich system. Fail fast, fail loud, except for the documented degradation paths (§10.2).

When in doubt, prefer the simpler architecture and defer.

---

## 15. Glossary of seams (one-liners)

- **Tool result envelope** — uniform dict shape; the only thing tools return.
- **Session workspace** — per-run host dir mounted into every container at `/workspace`.
- **Core skill** — `proteindesign.md`, concatenated into the system prompt at every run start; tool skills are Read on demand.
- **Self-evolution** — the agent appending durable lessons to its own skill files (append-only, git-tracked, reviewable via `proteinclaw skills`).
- **4-file convention** — every GPU tool is `tool.yaml` + `Dockerfile` + `implementation.py` + (universal) `tool_entrypoint.py` (+ optional `_normalize.py`).
- **Cascade** — ESMFold (cheap, monomer, filter) → AF2-multimer (expensive, complex, rank).
- **Complex pLDDT** — average pLDDT over the binder chain in the AF2-multimer prediction. The ranking signal.
- **Hit gate** — strict multi-metric AND threshold (pLDDT + ipSAE + ipTM + hotspot satisfaction + BSA) the agent uses to decide when to stop.
- **Research scout** — read-only Sonnet/Opus subagent for fanned-out literature/debate; cannot run the pipeline or write files.
- **Trace** — `trace.jsonl`; the reproducibility artifact (not a seed).
```


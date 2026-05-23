# PRD: `proteinclaw` — Agentic CLI for Protein Binder Design

**Status:** v1.0.0
**Owner:** Daanish Hindustani
**Last updated:** 2026-05-22

---

## 1. Summary

`proteinclaw` is a Python library + CLI that lets a computational biologist describe a binder-design goal in natural language (e.g., *"design a binder to PD-L1's IgV domain"*) and get back a ranked set of binder candidates — fully autonomously. A Claude-powered agent (via the **Claude Agent SDK**, billed against the user's Claude Pro/Max subscription credit pool) drives the campaign through an in-process MCP server that wraps the registered tool set; it plans the campaign, orchestrates **RFdiffusion3 → ProteinMPNN → ESMFold (fast monomer pre-filter) → AlphaFold2-multimer (binder+target complex prediction, the ranking signal)** on a local GPU workstation, triages designs by complex pLDDT, and produces an interactive HTML report alongside reproducible PDB + sequence outputs. (Host-side glue code outside the SDK boundary uses RestrictedPython for additional safety.)

The tool is an internal research tool, optimized for fast iteration.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Binder** | A small protein designed to bind a target protein at a specified epitope |
| **Target** | The protein of interest (e.g., PD-L1) the binder should attach to |
| **Epitope** | The region of the target the binder should contact |
| **Hotspots** | Specific residues on the target the binder must contact (e.g., `A54,A57,A61`) |
| **Backbone** | A 3D protein skeleton without side-chain identities; output of RFdiffusion3 |
| **MPNN** | ProteinMPNN — inverse-folding model that assigns amino-acid sequences to a backbone |
| **ESMFold** | Single-sequence structure predictor (Meta); used here as a fast monomer pre-filter |
| **AF2 / AlphaFold2** | DeepMind's structure predictor; in `proteinclaw` we use the **multimer** variant on binder+target |
| **pLDDT** | Predicted Local Distance Difference Test — per-residue confidence score (0–100); we use the average. ESMFold pLDDT and AF2 pLDDT are not directly comparable |
| **Complex pLDDT** | Average pLDDT over the binder chain in an AF2-multimer prediction of binder+target |
| **MSA** | Multiple Sequence Alignment; AF2 input. We fetch via the public ColabFold API |
| **RCSB / PDB** | Protein Data Bank — the source of experimental target structures |
| **UniProt** | Sequence/annotation database used to disambiguate target names |
| **Skill file** | `proteindesign.md` — domain knowledge loaded into the agent's system prompt |
| **Session ID** | Per-run identifier that lets tool outputs chain together via a shared host-mounted workspace |
| **Cascade** | The ESMFold-then-AF2-multimer two-stage validation pipeline |

Deferred to v2+: **iPAE** (interface PAE), **ddG** (Rosetta interface energy), **SC/SASA** (shape complementarity / solvent-accessible surface area), **LigandMPNN**, **RFdiffusion-AA**.

---

## 3. Goals & non-goals

### Goals

- Reduce the time from "I want a binder against X" to "ranked candidates ready for ordering" from days of manual pipeline-wrangling to a single autonomous run.
- Let researchers express intent in plain English; the agent does the rest (literature scan, structure fetch, epitope selection, model/hyperparam choice, execution, triage).
- Produce fully reproducible runs — every decision the agent made is logged.
- Be a foundation we can extend (more models, more metrics, more autonomy) without rewrites.

### Non-goals (v1)

- No multi-node / SLURM / cloud orchestration. Single local GPU node only.
- No wet-lab protocol or DNA-synthesis output.
- No self-iterating refinement loops beyond the user's `--rounds` budget.
- No support for inputs other than natural language (no direct PDB upload, UniProt ID, hotspot spec, etc.) in v1.
- No non-pLDDT scoring metrics in v1 (no iPAE, ddG, SC/SASA, self-consistency, novelty).
- No fallback if RCSB target resolution fails — fail fast with a clear error.

---

## 4. Target user & use case

**Primary user:** Computational biologists and ML researchers running binder-design campaigns. Comfortable on a CLI, fluent in PDB/Rosetta/AF concepts, want to spend their time on hypotheses — not on YAML config files and shell scripts.

**Canonical workflow:**

1. Researcher activates a local conda/uv env with `proteinclaw` installed.
2. Types `proteinclaw run "design a 60–90 residue binder to PD-L1's IgV domain, ~40 designs"`.
3. Agent prints its plan, then executes inside its sandbox.
4. When the campaign completes, the output directory contains ranked PDBs + sequences, a `run.db` row, and `report.html`.
5. Researcher opens the report (optionally with reasoning panel), picks top candidates, kicks off another round if desired.

---

## 5. User stories

- **As a researcher,** I want to launch a binder campaign with a single English sentence so I don't have to write configs.
- **As a researcher,** I want the agent to explain its plan before running so I can catch obvious mistakes.
- **As a researcher,** I want the agent to search recent literature for relevant binder-design strategies against my target so I benefit from published know-how.
- **As a researcher,** I want all designs ranked by pLDDT so I can quickly pick winners.
- **As a researcher,** I want a persistent run history so I can compare campaigns over weeks.
- **As a researcher,** I want to optionally see the agent's reasoning trace alongside the report so I can audit *why* it chose a hotspot or sampling temp.
- **As a researcher,** I want to cap the campaign at N rounds / N designs so it doesn't burn the GPU all weekend.

---

## 6. Functional requirements

### 6.1 Input

- **Sole input:** a natural-language prompt passed to `proteinclaw run "<prompt>"`.
- **Optional flags:**
  - `--rounds N` — max iteration rounds (**default: 2**).
  - `--max-designs N` — cap total designs across the campaign (**default: 80**, sized so the AF2-multimer survivors top-K is meaningful after the ESMFold filter).
  - `--output-dir PATH` — where to write artifacts.
  - `--dry-run` — print plan, do not execute.
  - `--show-reasoning` — emit a reasoning panel into `report.html` and stream agent thoughts to stdout.
- The agent parses the prompt to extract target identity, epitope/region, length/topology constraints, and scale.
- **Ambiguity handling:** The agent proceeds with its best guess on most ambiguity and logs all assumptions. **Exception: target resolution.** If the prompt is genuinely ambiguous between distinct biological entities — multiple PDB structures of the target with different bound partners or epitopes, multiple isoforms, or a name that maps to several UniProt IDs — the agent stops and asks one clarifying question with a short numbered menu. This is the only allowed interactive interruption.

### 6.2 Agent sandbox & tools

The agent runs inside a **RestrictedPython sandbox** — a constrained Python execution environment used purely for parsing/transforming data between tool calls and writing small glue scripts. The sandbox:

- **Allows:** standard library subset (`json`, `re`, `math`, `os.path`, `pathlib` read-only ops, `collections`), Biopython for PDB parsing, NumPy for light numerics, and the registered tool functions.
- **Blocks:** arbitrary file writes outside the run's `output-dir`, raw `subprocess`/`os.system`, network calls except through registered tools, `eval`/`exec` on non-sandboxed code, imports outside the allowlist.
- **Is not** where GPU models run. The tools the sandbox calls (`rfdiffusion3`, `proteinmpnn`, `esmfold`, `alphafold2_multimer`) dispatch out of the sandbox to Docker containers via the router (§9.4).

Each tool logs to `trace.jsonl`.

| Tool | Provider / source | Purpose |
|---|---|---|
| `web_search` | **DuckDuckGo Instant Answer + HTML scrape** (no API key) | General-purpose web search for context, protocols, troubleshooting |
| `literature_search` | **Semantic Scholar Graph API** (free, no key required for low volume) + bioRxiv API as fallback | Live search over recent biology / protein-design papers |
| `uniprot` | UniProt REST | Fetch sequences, domain annotations, cross-refs by accession or name |
| `pdb` | RCSB Data API + file service | Look up and download PDB entries by ID |
| `rcsb` | RCSB Search API | Search RCSB for structures matching a target description (primary entry point for target resolution) |
| `rfdiffusion3` | local Docker (GPU) | Run RFdiffusion3 backbone generation |
| `proteinmpnn` | local Docker (GPU) | Run ProteinMPNN sequence design |
| `esmfold` | local Docker (GPU) | **Fast monomer pre-filter:** predict binder-alone structure; cheap discard signal |
| `alphafold2_multimer` | local Docker (GPU) | **Ranking signal:** predict the **binder+target complex**; rank by complex pLDDT over the binder chain |
| `sandbox_exec` | in-process | Run arbitrary Python in the sandbox (file I/O, parsing PDBs, light numerics) |

**Provider notes & quota awareness:**
- Semantic Scholar's free tier has rate limits. The `literature.py` tool implements client-side throttling and caches results in the run's `literature.md`. If rate-limited, the agent logs and continues without literature input rather than failing.
- DuckDuckGo's HTML endpoint is brittle. The `web.py` tool catches scrape failures and returns `{"summary": "web search unavailable", "results": []}` so the agent can proceed without it.

### 6.3 Skill file: `proteindesign.md`

A single skill file ships with the package at `proteinclaw/skills/proteindesign.md`. **It is concatenated into the agent's system prompt at the start of every run** (not injected as a tool result, not lazy-loaded — it's part of the initial context the agent sees alongside the user's prompt). This makes domain knowledge stable across the conversation, costs context-window tokens once per run, and lets researchers edit one file to update agent behavior without touching code.

The skill file specifies, at minimum:

- **Which tool to call for what task** (target resolution → `rcsb`/`uniprot`/`pdb`; backbone → `rfdiffusion3`; sequences → `proteinmpnn`; pre-filter → `esmfold`; ranking → `alphafold2_multimer`).
- **The validation cascade:** ESMFold first on the binder alone as a fast pre-filter; AlphaFold2-multimer on the binder+target complex for ranking. The skill file describes the cascade and **leaves the ESMFold discard threshold up to the agent** — the agent inspects the ESMFold pLDDT distribution per round and decides what to keep, logging the threshold and reasoning. There is no PRD-mandated cutoff.
- **What signals to rank by:** average AF2-multimer pLDDT over the binder chain (the "complex pLDDT"). Per-residue pLDDT on the interface region is also surfaced for the agent to inspect.
- **Input/output schemas** for each tool, with examples.
- **Recommended default hyperparams** per stage (sampling temps, num seqs per backbone, length sweeps).
- **Common failure modes and recovery patterns** (OOM → reduce batch; missing weights → check Docker image; tool crash → retry once with adjusted params; ColabFold MSA timeout → retry once, then fall back to single-sequence mode for that design).
- **Literature-search prompts** the agent should run early in a campaign (e.g., "recent binders against {target}", "known hotspots on {epitope}").

The skill file is a living document — researchers can edit it to encode new lessons without touching agent code.

### 6.4 Target resolution

- The agent resolves the target via the `rcsb`, `uniprot`, and `pdb` tools.
- Resolution strategy (codified in the skill file):
  1. Disambiguate the target name with `uniprot` if needed.
  2. Search `rcsb` for structures; prefer high resolution, complete chain, recent deposition, presence of the named domain/epitope.
  3. Download with `pdb`; extract the relevant chain(s); crop to the requested domain if specified.
- **If multiple distinct biological entities match** (different epitopes, isoforms, bound partners), the agent asks one clarifying question with a numbered menu rather than guessing — see §6.1.
- **If RCSB returns no usable hit, the run fails fast** with a clear error and the agent's full reasoning. No AlphaFold DB fallback in v1.

### 6.5 Pipeline orchestration

The agent orchestrates models inside the sandbox:

| Stage | Tool | Input | Agent responsibility |
|---|---|---|---|
| Literature recon | `literature_search`, `web_search` | target name, epitope | Pull recent strategies / hotspots / pitfalls for the target |
| Target resolution | `rcsb`, `uniprot`, `pdb` | natural-language target | Resolve target structure; clarify if ambiguous (§6.4) |
| Backbone generation | `rfdiffusion3` | target PDB + hotspots + length | Pick hotspots, length range, sampling temp, num designs |
| Sequence design | `proteinmpnn` | backbone PDBs from RFD3 | Pick sampling temp, num seqs per backbone, fix target residues |
| Monomer pre-filter | `esmfold` | designed sequences (binder alone) | Predict binder-alone structure; agent inspects pLDDT distribution and decides what to discard |
| Complex ranking | `alphafold2_multimer` | concatenated `binder:target` sequence | Predict binder+target complex; rank survivors by complex pLDDT over the binder chain |

**Key change vs a monomer-only pipeline:** the ranking step predicts the **complex**, not the binder alone. A design that folds well in isolation but doesn't interact with the target will have high ESMFold pLDDT but low AF2-multimer complex pLDDT. This is the signal that actually correlates with binding (imperfectly, but far better than monomer pLDDT). Interface metrics (iPAE, ddG) are deferred to v2+.

The agent writes configs / scripts, runs each stage, parses outputs, and decides next steps. Errors are handled per the skill-file recovery patterns.

### 6.6 Triage & ranking

- Designs are ranked **by AlphaFold2-multimer complex pLDDT** — the average pLDDT over the binder chain in the predicted binder+target complex.
- ESMFold pLDDT (monomer) is stored for every design but used only as the agent-chosen pre-filter signal.
- Both values are surfaced in the report so users can spot designs that fold but don't dock.
- Top-K designs (default K=10) are flagged in the report.

### 6.7 Iteration

- Default `--rounds 2`: after round 1, the agent inspects results, decides whether a refinement pass is justified (e.g., narrower length range, different sampling temp, focused on best hotspots), and runs round 2. Its decision and reasoning are logged.
- `--rounds 1` disables iteration. `--rounds N > 2` allows deeper campaigns up to the user's budget.

### 6.8 Output

Each run produces an output directory:

```
runs/<run_id>/
  designs/
    rank_01_<id>.pdb
    rank_01_<id>.fasta
    ...
  report.html              # interactive: ranking table, per-design pLDDT (ESM + AF2), 3D viewer, optional reasoning panel
  plan.md                  # agent's initial plan
  trace.jsonl              # full agent trace: prompts, tool calls, decisions, errors
  literature.md            # summary of literature/web findings the agent used
  config/                  # all configs the agent generated for each pipeline stage
  raw/                     # raw outputs from each model (preserved for reproducibility)
```

And a row in the persistent SQLite DB.

### 6.9 Persistent run history

- A single SQLite DB at `~/.proteinclaw/runs.db` (path configurable).
- Schema (minimum):
  - `runs(run_id, session_id, prompt, target_pdb_id, target_chain, target_crop, started_at, ended_at, status, num_designs, output_dir, agent_model, git_sha)`
    - `target_pdb_id` is the RCSB accession (e.g. `5JDS`); `target_chain` is the chain ID used (`A`); `target_crop` is the residue range crop applied (`54-150` or `NULL` for full chain). `top_plddt_af2` is intentionally omitted — derive from `designs.plddt_af2_complex` when needed.
  - `designs(design_id, run_id, rank, plddt_esm_monomer, plddt_af2_complex, pdb_path, fasta_path)`
  - `agent_steps(step_id, run_id, step_idx, role, content, tool, tool_args, tool_result_summary, timestamp)`
- `proteinclaw history` lists past runs; `proteinclaw show <run_id>` opens the report.

### 6.10 Agent behaviors (LLM responsibilities)

The Claude-backed agent:

1. **Picks models and hyperparameters from natural language** — guided by `proteindesign.md`.
2. **Critiques and triages designs** using the ESM→AF2 pLDDT cascade.
3. **Writes and executes code** in the sandbox to glue stages together.
4. **Reasons over literature and prior runs** via `literature_search`, `web_search`, and the SQLite history.
5. **Handles error recovery & retries** per the recovery patterns in `proteindesign.md`.

---

## 7. Non-functional requirements

- **Hardware:**
  - **Minimum:** 1× NVIDIA GPU with 24 GB VRAM (e.g., RTX 3090, A10G, L4), 32 GB system RAM, 200 GB free disk for Docker images + model weight caches + run artifacts.
    - At 24 GB the runtime fits RFdiffusion3 and ProteinMPNN comfortably, ESMFold (16 GB) fits, AF2-multimer fits for small targets (<400 residue complex).
  - **Recommended:** 1× A100 / H100 (40–80 GB VRAM), 64 GB RAM, 500 GB disk. Required for AF2-multimer on larger targets (>400 residues in the complex) without OOM.
  - **Below minimum:** `proteinclaw doctor` warns and prints which tools will be unavailable; the agent disables them at planning time rather than failing mid-run.
- **Reproducibility:** Same prompt + same `proteinclaw` version + same Docker image digests → designs from the *same* RFD3/MPNN/AF2 sampling distributions. Exact bit-identical reproduction is not guaranteed because (a) the Claude agent's plan is nondeterministic and logged rather than pinned, and (b) the underlying models have internal sampling. **No `--seed` flag** is exposed; the trace is the reproducibility artifact.
- **Auditability:** Every agent decision is in `trace.jsonl`; `--show-reasoning` surfaces it in the report. A human should be able to reconstruct *why* the agent chose a given hotspot or sampling temp.
- **Failure modes:** Fail fast and loud. Never silently fall back to a degraded pipeline.
- **Footprint:** Installable via `pip install proteinclaw` (or `uv add`). Model weights live in host-mounted caches (§9.6), pulled lazily on first use.

---

## 8. Architecture sketch

```
┌────────────────────────────────────────────────────────────────────┐
│                       proteinclaw CLI                              │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│  Agent Core (Claude Agent SDK)  +  proteindesign.md skill file     │
│  (skill file concatenated into system prompt on every run)         │
│  - Plan generation                                                 │
│  - Tool selection & invocation (inside RestrictedPython sandbox)   │
│  - Triage & iteration decisions                                    │
└─┬──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌────────────────────────────────────────────────────────────────────┐
│                  RestrictedPython Sandbox                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ web_search   │  │ literature_  │  │ uniprot / pdb / rcsb     │ │
│  │ (DuckDuckGo) │  │ search       │  │                          │ │
│  │              │  │ (Semantic    │  │                          │ │
│  │              │  │  Scholar)    │  │                          │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐ │
│  │ rfdiffusion3 │  │ proteinmpnn  │  │ esmfold    │  │ af2_     │ │
│  │ (Docker)     │  │ (Docker)     │  │ (Docker)   │  │ multimer │ │
│  │ backbones    │  │ sequences    │  │ monomer    │  │ (Docker) │ │
│  │              │  │              │  │ pre-filter │  │ complex  │ │
│  │              │  │              │  │            │  │ ranking  │ │
│  └──────────────┘  └──────────────┘  └────────────┘  └──────────┘ │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ sandbox_exec — RestrictedPython for parsing / glue logic   │   │
│  └────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                │
                ▼
        ┌────────────────┐
        │ SQLite history │
        │ + run outputs  │
        └────────────────┘
```

Each tool has typed inputs/outputs and logs to `trace.jsonl`. Model tools delegate to Docker containers so weights and dependencies are pinned per model. See §9 for the mandatory 4-file-per-tool convention every model wrapper must follow.

---

## 9. Implementation

This section locks in the conventions every tool in `proteinclaw` must follow. The pattern is adopted from `celltype-agent`'s container-tool layout, trimmed to single-node local execution.

### 9.1 Repository layout

```
src/proteinclaw/
  agent/                       # Claude Agent SDK loop, planner, skill loader, in-process MCP
  tools/
    __init__.py                # ToolRegistry + @register decorator
    _container_tools.py        # auto-discovery of tool.yaml files
    rfdiffusion3/              # GPU tool (Docker) — backbone generation
      tool.yaml
      Dockerfile
      implementation.py
      tool_entrypoint.py
    proteinmpnn/               # GPU tool (Docker) — sequence design
      tool.yaml
      Dockerfile
      implementation.py
      tool_entrypoint.py
    esmfold/                   # GPU tool (Docker) — monomer pre-filter
      tool.yaml
      Dockerfile
      implementation.py
      tool_entrypoint.py
    alphafold2_multimer/       # GPU tool (Docker) — complex ranking
      tool.yaml
      Dockerfile
      implementation.py
      tool_entrypoint.py
    uniprot.py                 # plain-Python tool, requires_gpu=False
    pdb.py
    rcsb.py
    literature.py
    web.py
    sandbox_exec.py
  runner/
    local.py                   # Docker dispatcher (LocalRunner)
    router.py                  # local-only ComputeRouter w/ VRAM checks
  skills/
    proteindesign.md           # ESM→AF2 cascade, thresholds, recipes
  cli.py                       # `proteinclaw run "..."`
```

### 9.2 The 4-file-per-tool convention (MANDATORY for every GPU model)

Every model tool (`rfdiffusion3`, `proteinmpnn`, `esmfold`, `alphafold2_multimer`, and any future model) lives in its own directory containing **exactly four files**. Adding a new model means creating one directory; no other code changes — auto-discovery picks it up at startup.

```
src/proteinclaw/tools/<tool_name>/
  tool.yaml             # metadata + JSON-Schema parameters + compute requirements
  Dockerfile            # pinned environment + clone of upstream model repo
  implementation.py     # the actual run(**kwargs) -> dict (runs inside the container)
  tool_entrypoint.py    # universal shim: read input.json → call run() → write output.json
```

#### File 1: `tool.yaml`

The single source of truth for each tool. It serves three roles:

- Validates LLM-generated args (the `parameters` block is plain JSON Schema).
- Generates the tool description injected into the agent's planner prompt.
- Tells the router what compute the tool needs (GPU, VRAM, timeout).

Required fields:

```yaml
name: design.rfdiffusion3         # dotted name; first segment = category
display_name: RFdiffusion3
description: <one-line description shown to the agent>
category: design                  # design | structure | data | etc.
usage_guide: <when the agent should pick this tool>
docker_image: proteinclaw/rfdiffusion3:latest
parameters:                       # JSON Schema — required + properties
  type: object
  additionalProperties: false
  required: [target_pdb, hotspot_residues, binder_length]
  properties:
    target_pdb:        { type: string, description: "..." }
    binder_length:     { type: integer, minimum: 30, maximum: 200 }
    hotspot_residues:  { type: string, description: "A54,A57,A61" }
    num_designs:       { type: integer, default: 10, minimum: 1, maximum: 100 }
    diffusion_steps:   { type: integer, default: 50, minimum: 10, maximum: 90 }
compute:
  requires_gpu: true
  min_vram_gb: 24                 # conservative; see §9.6 hardware notes
  gpu_profile: structure
execution:
  timeout_s: 600
```

**`min_vram_gb` per tool (v1, must match `proteinclaw doctor` checks):**

| Tool | `min_vram_gb` | Reasoning |
|---|---|---|
| `design.rfdiffusion3` | 24 | Comfortable on 24GB cards for binders <150 residues; bump if target complex is large |
| `design.proteinmpnn` | 12 | Lightweight; could run on smaller cards but 12 is the floor we test against |
| `structure.esmfold` | 16 | Meta's spec; works on 16GB cards for sequences <600 residues |
| `structure.alphafold2_multimer` | 24 | Floor for small complexes; **recommended 40+** for binder+target complexes >400 residues |

These are the values that ship in `tool.yaml`. The router uses them to decide whether to attempt local execution or fail with a clear error.

#### File 2: `Dockerfile`

Pinned environment. Conventions:

- Base on `nvidia/cuda:<version>-runtime-ubuntu22.04`.
- Install only the upstream model's deps. Don't vendor — `git clone --depth 1` the upstream repo into `/opt/<model>`.
- Do **not** bake weights into the image. Weights download lazily on first run and live in host-mounted caches (see §9.6).
- Copy `tool_entrypoint.py` and `implementation.py` to `/opt/`.
- `ENTRYPOINT ["python3", "/opt/tool_entrypoint.py"]`.

#### File 3: `tool_entrypoint.py`

The universal shim — **identical across every tool**:

```python
#!/usr/bin/env python3
"""Universal container entrypoint. Reads input.json, calls implementation.run(**args), writes output.json."""
import json, os, sys, traceback

def main():
    input_file = os.environ.get("INPUT_FILE", "/workspace/input.json")
    output_file = os.environ.get("OUTPUT_FILE", "/workspace/output.json")
    try:
        with open(input_file) as f:
            args = json.load(f) or {}
        sys.path.insert(0, "/opt")
        from implementation import run
        result = run(**args)
        if not isinstance(result, dict):
            result = {"summary": str(result)}
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
    except Exception as e:
        with open(output_file, "w") as f:
            json.dump({"summary": f"Error: {e}", "error": traceback.format_exc()}, f, indent=2)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

The only contract between host and container is **JSON in, JSON out via the `/workspace` mount.**

#### File 4: `implementation.py`

A plain Python module with exactly one entry point: `run(**kwargs) -> dict`. The skeleton every implementation must follow:

```python
"""<Tool name> — wraps <upstream model>. Hardware: <GPU>, <VRAM> GB."""
import os, subprocess, sys, tempfile, threading, time

def _vram_mb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=5)
        return int(out.strip().split("\n")[0])
    except Exception:
        return 0

def _monitor_vram(stop_event, results):
    peak = 0
    while not stop_event.is_set():
        v = _vram_mb()
        if v > peak: peak = v
        results["peak"] = peak
        stop_event.wait(0.5)

def normalize_args(args: dict) -> dict:
    """Validate & coerce inputs. Raise ValueError on invalid input."""
    # ...
    return args

def run(<typed args>, session_id: str = "", **kwargs) -> dict:
    try:
        normalized = normalize_args({...})
    except ValueError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args"}

    t0 = time.time()
    vram_before = _vram_mb()
    stop = threading.Event(); results = {"peak": vram_before}
    mon = threading.Thread(target=_monitor_vram, args=(stop, results), daemon=True); mon.start()

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Write inputs to tmpdir
        # 2. Ensure weights are cached (lazy download if missing)
        # 3. subprocess.run() the upstream CLI, OR call upstream as a library
        # 4. Parse outputs from tmpdir
        ...

    stop.set(); mon.join(timeout=2)

    return {
        "summary": "<human-readable one-liner including key metrics>",
        # tool-specific fields (e.g. designs, sequences, pdb_content, confidence, ...)
        "metrics": {
            "vram_before_mb": vram_before,
            "vram_peak_mb": results["peak"],
            "time_total_s": round(time.time() - t0, 2),
        },
    }
```

### 9.3 Result envelope (uniform across all tools)

Every `run()` — Docker tool or plain-Python tool — returns a dict with this shape so the agent's triage logic never needs per-tool special cases:

```python
# Success:
{
  "summary": str,              # required — one-line human description
  "metrics": dict,             # required for GPU tools — vram/time
  "session_id": str,           # required for tools that write artifacts (see below)
  # tool-specific fields:
  # ProteinMPNN          → sequences: List[str], scores: List[float], num_sequences: int
  # RFdiffusion3         → designs: List[Path], num_designs: int  (paths to PDB files in workspace)
  # ESMFold              → pdb_path: Path, confidence: float (monomer pLDDT 0-100), num_residues: int
  # AlphaFold2-multimer  → complex_pdb_path: Path, complex_confidence: float (binder-chain pLDDT 0-100),
  #                        binder_chain: str, target_chain: str, num_residues: dict
}

# Error:
{
  "summary": "Error: <short reason>",
  "error": "<traceback or canonical error code>",
  "metrics": dict,             # included if partial execution occurred
}
```

**`session_id` is first-class.** Every run has a unique `session_id` (UUID4 hex prefix). The host-side runner creates a per-session workspace directory at `~/.proteinclaw/gpu-workspace/<session_id>/` and mounts it into every container at `/workspace`. Tools write their outputs to `/workspace/<tool>_<step>/` rather than into the JSON response. The returned envelope contains **paths to artifacts in the workspace**, not the bytes themselves. This is the breadcrumb that lets one tool's output (e.g., RFdiffusion3's backbones) become the next tool's input (e.g., ProteinMPNN's `backbone_pdb`) without round-tripping multi-MB PDB strings through the LLM's context window.

The `session_id` is passed as an env var to the container (`SESSION_ID`); each `implementation.py` reads it and writes outputs to the agreed path layout. **Never return PDB bytes in the JSON envelope** — return paths.

### 9.4 Registry, router, and the dispatch path

The registry treats Docker-backed tools and plain-Python tools identically:

```
LLM tool call
   ↓
Agent (Claude Agent SDK) → in-process MCP server → registry.get_tool(name)
   ↓
ComputeRouter.route(tool, **kwargs)        # local-only in v1
   ↓ requires_gpu?
   ├─ No  → tool.function(**kwargs)        # direct in-process call (uniprot, pdb, etc.)
   └─ Yes → LocalRunner.run(tool, **kwargs)
              ↓
              ensure Docker image (build from tool dir if missing)
              ↓
              docker run --gpus all
                -v <session_workspace>:/workspace
                -v ~/.cache/huggingface:/root/.cache/huggingface
                -v ~/.cache/rfdiffusion:/root/.cache/rfdiffusion
                -v ~/.cache/proteinmpnn:/root/.cache/proteinmpnn
                -v ~/.cache/openfold:/root/.cache/openfold
                -e INPUT_FILE=/workspace/input.json
                -e OUTPUT_FILE=/workspace/output.json
                <docker_image>
              ↓
              tool_entrypoint.py reads input.json
              ↓
              implementation.run(**args)
              ↓
              writes output.json
              ↓
              LocalRunner reads output.json → returns dict to agent
```

Key responsibilities:

- **`tools/__init__.py`** — defines `Tool` dataclass, `ToolRegistry`, and the `@register` decorator. Holds the global `registry` singleton. Generates tool descriptions for the LLM planner.
- **`tools/_container_tools.py`** — at startup, walks `src/proteinclaw/tools/*/tool.yaml`, parses each, and registers a **placeholder function** for each container tool. The placeholder body is never executed; the router intercepts it. *Adding a new model = creating one directory; no registration code to edit.*
- **`runner/router.py`** — `ComputeRouter.route()`. Detects local GPU(s) via `nvidia-smi` (cached for session), compares against `min_vram_gb`, dispatches to `LocalRunner` or returns a structured error if the local GPU can't handle it. **No cloud routing in v1.**
- **`runner/local.py`** — `LocalRunner.run(tool, **kwargs)`. Per-session workspace at `~/.proteinclaw/gpu-workspace/<session_id>/`, lazy `docker build` from the tool directory if the image isn't present locally, host weight-cache mounts, `--gpus all`, JSON I/O, parse stdout/stderr on container failure.

### 9.5 Plain-Python tools (`uniprot`, `pdb`, `rcsb`, `literature`, `web`)

Non-GPU tools skip the Docker layer entirely. They live as single `.py` files in `src/proteinclaw/tools/` and use the same `@register` decorator as the container tools:

```python
from proteinclaw.tools import registry

@registry.register(
    name="data.uniprot_fetch",
    description="Fetch a UniProt entry by accession or name.",
    category="data",
    parameters={
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
    },
    requires_gpu=False,
)
def uniprot_fetch(query: str, **kwargs) -> dict:
    # ... http call ...
    return {"summary": f"UniProt: found {accession}", "sequence": seq, "domains": domains}
```

The agent sees them as identical `Tool` objects to the GPU tools — same description format, same JSON-Schema params, same result envelope.

### 9.6 Weight & data caches (host-side, mounted into containers)

To avoid re-downloading multi-GB weights every container run, the runner mounts host cache directories into every GPU container:

| Host path | Container path | Used by |
|---|---|---|
| `~/.cache/huggingface` | `/root/.cache/huggingface` | ESMFold (via `transformers`) |
| `~/.cache/rfdiffusion` | `/root/.cache/rfdiffusion` | RFdiffusion3 |
| `~/.cache/proteinmpnn` | `/root/.cache/proteinmpnn` | ProteinMPNN |
| `~/.cache/openfold` | `/root/.cache/openfold` | AlphaFold2 (params + alignments) |

Implementations look for weights at the container paths; if missing, they download lazily on first run. After that, all runs are offline.

### 9.7 Conventions every tool must follow

- **One `run(**kwargs) -> dict` per `implementation.py`.** No module-level work; no side effects on import.
- **`normalize_args()` separate from `run()`.** Raises `ValueError` on bad input; `run()` catches and returns `{"error": "invalid_args"}`.
- **Always return the result envelope** (§9.3). Never raise out of `run()` — convert to `{"error": ...}`.
- **Background VRAM monitor thread** for all GPU tools. Cheap, hugely useful for OOM debugging.
- **Lazy weight handling.** Implementations check the cache path; if absent, download once. Never bake weights into the Docker image.
- **No host paths in `tool.yaml`.** All paths are container-internal. Host paths are owned by the runner.
- **Tool name format: `<category>.<tool>`** (e.g. `design.rfdiffusion3`, `structure.esmfold`, `structure.alphafold2_multimer`). The category prefix groups tools in the planner prompt.

### 9.8 Adding a new tool (developer flow)

1. `mkdir src/proteinclaw/tools/<new_tool>/`.
2. Write `tool.yaml` with the schema and compute block.
3. Write `Dockerfile` (clone upstream repo, install deps).
4. Copy `tool_entrypoint.py` from any existing tool directory (it's identical).
5. Write `implementation.py` with `normalize_args()` and `run()`.
6. Restart the agent — auto-discovery registers it. Run `proteinclaw doctor` to verify the image builds.

No edits to the registry, router, runner, or agent code are needed.

### 9.9 Per-tool implementation notes (from `celltype-agent`)

Quick notes on what each reference implementation does, what's worth copying, and what to change for `proteinclaw`. These are observations from reading the celltype-agent source — not the final spec for our wrappers.

#### ProteinMPNN (sequence design)

- **Invocation style:** `subprocess.run()` against the upstream `protein_mpnn_run.py` CLI. Implementation is ~95 lines and very clean.
- **Inputs:** raw PDB content as a string (written to a tmpdir), `num_sequences`, `sampling_temp` (hardcoded 0.1 in the reference — should be a real parameter for us), `--batch_size min(num_sequences, 8)`, `--seed 42`.
- **Weights:** `vanilla_model_weights/` shipped with the upstream repo clone. On first run, the implementation copies them from `/opt/ProteinMPNN/vanilla_model_weights` into `/root/.cache/proteinmpnn/vanilla_model_weights` so subsequent runs read from the mounted host cache. Clever — uses the upstream repo itself as the weight source.
- **Output parsing:** walks `<out>/seqs/*.fa`, skips the `sample=0` line (which is the input sequence echo, not a design), parses `score=` from FASTA headers. Returns `sequences`, `scores`, `num_sequences`.
- **VRAM monitoring:** background thread polling `nvidia-smi` every 0.5s. Light and reusable.
- **Timeout:** 120s on the subprocess (aggressive — fine for small backbones, tight for >200 residues at high `num_sequences`).
- **Docker:** `nvidia/cuda:12.1.0-runtime-ubuntu22.04`, Python 3.11, torch ≥2.4, biopython. Clones upstream at build time. Small image.
- **What we change for `proteinclaw`:**
  - Expose `sampling_temp` as a real param (the YAML says it's configurable; the implementation ignores it).
  - Bump subprocess timeout to match the `tool.yaml` `execution.timeout_s` (300s).
  - Add `fix_positions` / `chain_id` for binder-design workflows (keep target residues fixed while redesigning the binder chain).

#### RFdiffusion3 (backbone generation)

- **Invocation style:** `subprocess.run()` against `RFdiffusion/scripts/run_inference.py` with Hydra-style overrides (`contigmap.contigs=[...]`, `ppi.hotspot_res=[...]`, `inference.num_designs=N`, `diffuser.T=N`).
- **Inputs:** PDB text inline (the implementation explicitly refuses host file paths from outside `/workspace` — good security model). Two modes: `monomer` (free backbone) and `binder` (target-conditioned). Binder mode requires `receptor_chain`, `binder_length`, and `hotspot_residues` in canonical `A54,A57` form. There's careful `normalize_args()` validation.
- **Hotspot parsing:** `_parse_hotspot_residues()` enforces `[A-Z]\d+` format and validates every hotspot uses the declared `receptor_chain`. This is the kind of input hygiene we want — would have been easy to skip and burn a 5-min GPU run on garbage.
- **Chain-range extraction:** `_parse_chain_ranges()` reads PDB ATOM lines and builds `{chain_id: (min_resi, max_resi)}`. Used to build the `contigmap.contigs` string (`[binder_length-binder_length/0 A1-200]`).
- **Weights:** lazy `urllib.request.urlretrieve` from `http://files.ipd.uw.edu/pub/RFdiffusion/...`, with a magic-byte sanity check (`PK\x03\x04` for zip or `\x80` for pickle) before reuse. Cached at `/root/.cache/rfdiffusion`. `binder` mode requires `Complex_base_ckpt.pt` in addition to `Base_ckpt.pt`.
- **Output parsing:** walks the output dir for `*.pdb`, truncates each PDB to 3000 chars (probably to fit in LLM context — we'd remove this and save full PDBs to disk, returning paths). Counts ATOM lines per design as a sanity check.
- **Docker:** `nvcr.io/nvidia/pytorch:24.07-py3`, pinned `e3nn==0.3.3`, `hydra-core==1.3.2`, `dgl` (with PyTorch 2.4 / CUDA 12.4 wheel), `SE3Transformer` built from the upstream `env/` directory, `DGLBACKEND=pytorch`. RFdiffusion has notoriously fussy deps; this Dockerfile is the result of someone fighting through them — worth copying line-by-line.
- **What we change for `proteinclaw`:**
  - **Rewrite for RFdiffusion3** (different repo, different invocation, different weight URLs). The `normalize_args()` / hotspot-validation / chain-range scaffolding is fully reusable; only the `cmd = [...]` block and `_required_checkpoint_names()` need to be redone.
  - Don't truncate PDB output strings — save full files to the session workspace and return paths in the result envelope. The agent doesn't need the PDB bytes in context.

#### ESMFold (fast structure validation — pre-filter)

This is the one you specifically called out, and it has a different shape from the others.

- **Invocation style:** **in-process Python**, not subprocess. Imports `transformers.EsmForProteinFolding` directly inside `run()`. No upstream repo clone, no CLI shelling. The whole inference is ~20 lines.
- **Inputs:** a single amino-acid sequence string. FASTA-style input is auto-stripped (leading `>` lines removed). That's the entire input surface — no MSA, no templates, no databases.
- **Lazy import with graceful fallback:** the `import torch, transformers` block is wrapped in a broad `try/except` that returns a placeholder result if libraries are missing. **This is a smell.** It silently returns `confidence: 0` and a stub PDB instead of erroring out, which means a misconfigured environment could quietly poison a whole campaign. We should change this to a hard error.
- **Confidence:** averages the per-residue pLDDT tensor and multiplies by 100. This is the **same `confidence` field AlphaFold2 returns**, so the agent can compare ESM and AF2 pLDDT directly using one field name. Worth preserving.
- **Output:** tries `model.output_to_pdb(output)[0]` first (the HF helper); falls back to manually building a `Protein()` object from `aatype`, `positions[-1]`, `atom_mask`, and the pLDDT tensor as B-factors. The fallback is there because `output_to_pdb` was added in a later `transformers` version.
- **Metrics:** more granular than the other tools — separates `vram_before_model_load`, `vram_after_model_load`, `vram_peak`, plus `time_model_load` and `time_inference`. Useful when you're running ESMFold hundreds of times as a filter and want to know whether model load or inference dominates.
- **Weights:** HuggingFace cache. `facebook/esmfold_v1` downloads to `~/.cache/huggingface` (host-mounted). First call is slow (~1 min download + load); subsequent calls in the same container reuse the loaded model... except they don't, because the model is loaded inside `run()`, so each container invocation re-loads it. Wasteful.
- **Session writeback:** if a `session_id` is passed, writes the predicted PDB to `/vol/workspace/<session_id>/predicted_structure.pdb`. Useful for cross-tool handoff.
- **Docker:** `nvcr.io/nvidia/pytorch:25.04-py3`. Just `pip install transformers accelerate biopython numpy`. The smallest Dockerfile of the four — no upstream repo, no exotic deps.
- **What we change for `proteinclaw` (most important changes):**
  - **Kill the silent fallback.** Missing torch/transformers should return `{"error": "esmfold_libraries_missing"}`, not a stub PDB with `confidence: 0`. The agent could otherwise rank a bad design highly because all the placeholders tied.
  - **Hoist the model load.** Cache the loaded `EsmForProteinFolding` at module scope so the second call within the same container reuses it. ESMFold is our pre-filter — we'll call it many times per round. Reloading the 3GB model each call would be a major waste.
  - **Batch mode.** Add `sequences: List[str]` so the agent can submit a batch of MPNN-designed sequences in one container invocation. With model load amortized and batched inference, this drops ESMFold from "many seconds per design" to "many designs per second."
  - **Cap sequence length** (the YAML says 1024; enforce it in `normalize_args`).
  - **The two-stage pLDDT extraction (HF helper → manual fallback) is worth keeping.** It's defensive against `transformers` version drift.

#### AlphaFold2-multimer (complex ranking — primary signal)

**Note:** `celltype-agent` has both `alphafold2/` and `alphafold2-multimer/` tools. For `proteinclaw` v1 we use **multimer only** as the ranking signal, because predicting the binder+target complex is what actually tells us whether the design might bind. Monomer AF2 only tells us the binder folds in isolation — necessary but not sufficient.

- **Invocation style:** `subprocess.run()` against OpenFold's multimer config of `run_pretrained_openfold.py`. Same Docker base as the monomer tool; differs in inputs (paired sequences) and the model config preset (`model_1_multimer_v3` or similar).
- **Inputs:** the binder sequence and the target sequence as separate chains. The agent constructs the input by concatenating `>binder\n<MPNN sequence>\n>target\n<target sequence>` into the FASTA. Strict amino-acid regex per chain; no ambiguity codes.
- **MSA strategy:** ColabFold API for each chain separately, then paired into the multimer A3M format that OpenFold expects. This is the **slow step** of the cascade — typically 30-90s per chain for ColabFold's queue, then ~30-180s of inference. AF2-multimer dominates the campaign runtime; the ESMFold pre-filter exists primarily to keep AF2 invocations low.
- **Params:** OpenFold multimer params (~5GB) downloaded once via `download_alphafold_params.sh` into `/root/.cache/openfold/params/`. Host-mounted; persists across runs.
- **Templates:** disabled. Fine for binder design.
- **Relaxation:** off by default. Adds 1-5 min per structure with marginal benefit for ranking.
- **Output parsing:** walks the output dir for `.pdb`, identifies the binder chain (by chain ID — the order is preserved from the FASTA), averages B-factors over the binder chain's CA atoms → **complex pLDDT (binder chain)**. This is the ranking signal.
- **Docker:** same base as monomer AF2 — `nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04` + Miniforge + OpenFold's env. The largest of the five images at ~10GB.
- **What we do for `proteinclaw`:**
  - **Trim the YAML parameter surface** to what we actually use: `binder_sequence`, `target_sequence`, `relax_prediction`, `msa_source` (`colabfold | single_sequence`).
  - **`msa_source: single_sequence` fallback.** If ColabFold errors or times out on either chain, retry once, then fall back to single-sequence MSA for that chain. Log clearly — single-sequence AF2-multimer is noticeably worse and the agent should know.
  - **Multimer-only.** No `:` -trick monomer mode in this tool. If the agent wants monomer prediction it calls ESMFold.
  - **Return the full complex PDB path** (workspace artifact, not bytes) plus per-chain pLDDT averages.
  - Keep the OpenFold Dockerfile largely as-is. It's painful but it works.

#### Cross-cutting observations

A few patterns worth lifting verbatim across all four implementations:

- **`normalize_args()` is always a separate function** that raises `ValueError`, and `run()` catches and converts to `{"error": "invalid_args"}`. Clean separation, easy to unit-test.
- **The VRAM monitor thread is copy-paste-identical** in RFdiffusion and AlphaFold2 (and is a near-clone in ProteinMPNN). Pull it into a `proteinclaw.tools._gpu_metrics` shared module. (See §9.10.)
- **Every implementation uses `tempfile.TemporaryDirectory()`** as the I/O scratch dir, so the container's filesystem is always clean. Outputs that need to survive go to `/workspace/<session_id>/<tool>_<step>/` (host-mounted), not the tmpdir. Tools return paths, not bytes.
- **Errors return a dict; they never raise.** This is the contract that lets the agent loop work — every tool call resolves to a structured dict it can read.
- **`session_id` is first-class (see §9.3).** Tools read it from the `SESSION_ID` env var and write artifacts under the per-session workspace mount. This is how one tool's output (e.g., RFdiffusion3 backbones) becomes the next tool's input (e.g., ProteinMPNN's `backbone_pdb`) without bytes going through the agent's context window.

### 9.10 v1 deviations from the `celltype-agent` reference

The following deliberate departures from `celltype-agent` apply across all four model tools. Captured here so a developer porting code doesn't reintroduce the problems:

1. **Hoist the ESMFold model load** out of `run()` into module scope so it's reused across calls in the same container. `celltype-agent` reloads the ~3GB model every call — this is unaffordable when ESMFold is our pre-filter.
2. **Batch ESMFold.** Add `sequences: List[str]` so the agent submits batches of designs in one container invocation. Combined with #1, drops ESMFold from many-seconds-per-design to many-designs-per-second.
3. **Kill silent fallbacks.** `celltype-agent`'s ESMFold returns a stub PDB with `confidence: 0` if torch/transformers are missing. `proteinclaw` returns `{"error": "esmfold_libraries_missing"}` and the agent disables ESMFold for the rest of the run.
4. **Trim AF2-multimer YAML.** Only expose params the implementation actually honors: `binder_sequence`, `target_sequence`, `relax_prediction`, `msa_source`. No advertising of unimplemented features.
5. **Tools return paths, not bytes.** `celltype-agent` truncates PDB output to 3000 chars to fit LLM context. `proteinclaw` always writes full PDBs to the session workspace and returns the path. The agent reads the file via `sandbox_exec` only when it specifically needs structural detail.
6. **Shared `_gpu_metrics` module.** Pull the VRAM-monitor thread (copy-pasted across 3 of 4 celltype-agent tools) into `proteinclaw.tools._gpu_metrics` and import.
7. **Strip cloud routing.** `celltype-agent`'s `ComputeRouter` does local-vs-cloud dispatch. `proteinclaw` is local-only; we keep only the GPU-detect + VRAM-check + Docker-availability error paths.

### 9.11 Testing convention

Each tool ships with a tiny golden-output integration test under `tests/tools/<tool_name>/`:

```
tests/tools/proteinmpnn/
  test_proteinmpnn.py          # pytest, marked @pytest.mark.gpu
  fixtures/
    backbone.pdb               # tiny PDB input (1 design, ~50 residues)
    expected_summary.json      # known-good summary line + score range
```

Conventions:

- Each test runs the tool's `run(**kwargs)` end-to-end inside its Docker container (i.e. through `LocalRunner`).
- Tests are marked `@pytest.mark.gpu` and skipped by default; CI runs them on a GPU-enabled runner.
- Tests assert **soft-bound ranges** on stochastic outputs (e.g. `0.0 <= score <= 5.0`, `confidence > 50`) rather than exact values — model outputs aren't bit-stable across CUDA versions.
- Tests must pass on a fresh checkout with weights downloaded from scratch (no pre-warmed cache). This is the integration test for the lazy-weight-download path.
- `proteinclaw doctor --self-test` runs the full suite end-to-end and is the user-facing "is my installation healthy" check.

Beyond tool-level tests, integration tests cover:

- The dispatch path (registry → router → runner → container → result envelope).
- The session workspace handoff (tool A writes a path, tool B reads it).
- Skill-file loading (the system prompt contains the file's contents).
- SQLite schema migration on `proteinclaw upgrade`.

---

## 10. CLI surface (v1)

```
proteinclaw run "<prompt>" [--rounds N=2] [--max-designs N=80] [--output-dir PATH]
                           [--dry-run] [--show-reasoning]
proteinclaw history [--limit N] [--target X]
proteinclaw show <run_id>          # opens report.html
proteinclaw cancel <run_id>        # stops a running campaign
proteinclaw config                 # show / edit ~/.proteinclaw/config.toml
proteinclaw doctor                 # check GPU, Docker, weights, deps, free disk
proteinclaw doctor --self-test     # runs the full tool-level integration test suite
```

`proteinclaw doctor` checks (see also §7 hardware spec):

1. **NVIDIA GPU present** and `nvidia-smi` reports a valid driver. Print the GPU name + VRAM.
2. **VRAM ≥ 24 GB** (minimum) or warn. If <24 GB, list which tools will be disabled at planning time.
3. **Docker installed** and `docker info` works without sudo (or instructions to add the user to the `docker` group).
4. **NVIDIA Container Toolkit** working — `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi` succeeds.
5. **Free disk** ≥ 200 GB on the partition holding `~/.proteinclaw/` and `~/.cache/`.
6. **Network reachability** for RCSB, UniProt, Semantic Scholar, DuckDuckGo, ColabFold (informational; failure isn't fatal but the agent will be limited).
7. **Anthropic API key** present in env (`ANTHROPIC_API_KEY`) or `config.toml` (`[anthropic] api_key = "..."`). Used by the Claude Agent SDK; billed against the user's Claude Pro/Max subscription credit pool.
8. **Cached weights** — list which model weight caches exist and their size.

`proteinclaw doctor` exits non-zero if any of 1–4, 7 fails. The CLI refuses `proteinclaw run` until doctor passes.

Python API (for notebook use):

```python
from proteinclaw import run, history

result = run("design a binder to PD-L1's IgV domain", rounds=2)
result.top_designs   # → List[Design]
result.report_path   # → Path
result.reasoning     # → str  (full trace, optional)
```

---

## 11. Success criteria

- A researcher unfamiliar with the codebase can install `proteinclaw`, run `proteinclaw doctor` to green, run the canonical PD-L1 example, and get a ranked report without editing any config file.
- 80%+ of campaigns complete without manual intervention.
- Every completed run is fully reproducible from its `trace.jsonl`, `config/` directory, and Docker image digests.
- The team chooses to use it for real binder-design work — measured by ≥1 design from `proteinclaw` being ordered for wet-lab synthesis.
- All tool-level integration tests pass on a fresh checkout via `proteinclaw doctor --self-test`.

---

## 12. Tasks (build plan)

Milestones are task-numbered, not time-bound. Each task is independently mergeable.

**Task 1 — Tool wrapper skeleton.** Establish the 4-file convention (§9.2), the registry, `_container_tools.py` auto-discovery, the `LocalRunner` Docker dispatcher, and the `ComputeRouter` GPU/VRAM check. Land one trivial GPU tool end-to-end (e.g., a minimal "echo VRAM via nvidia-smi" container) to prove the dispatch path. Includes `proteinclaw doctor`.

**Task 2 — ProteinMPNN tool.** Port `celltype-agent`'s ProteinMPNN with the v1 deviations from §9.10 applied. Ship integration test (`tests/tools/proteinmpnn/`). The simplest model tool — good warm-up for the convention.

**Task 3 — ESMFold tool.** Port with hoisted model load, batched `sequences: List[str]`, no silent fallbacks. Ship integration test. This is the highest-leverage GPU tool because it's called the most.

**Task 4 — RFdiffusion3 tool.** Write from scratch (no celltype-agent reference). Reuse the `normalize_args` / hotspot validation / chain-range scaffolding from `celltype-agent`'s RFdiffusion v1 implementation. Ship integration test.

**Task 5 — AlphaFold2-multimer tool.** Port `celltype-agent`'s AF2 monomer wrapper but configure for multimer (paired MSAs via ColabFold, multimer model preset, complex-pLDDT extraction over the binder chain). Trim YAML per §9.10. `msa_source: single_sequence` fallback. Ship integration test. This is the biggest single task.

**Task 6 — Data tools.** Implement plain-Python tools: `uniprot`, `pdb`, `rcsb`, `literature_search` (Semantic Scholar), `web_search` (DuckDuckGo). All non-GPU. Cache responses in the session workspace. Ship unit tests with recorded fixtures.

**Task 7 — RestrictedPython sandbox.** Configure the sandbox per §6.2 (allow-list, blocks, tool exposure). Implement `sandbox_exec` tool. Integration tests covering escapes (`subprocess`, `open` outside workspace, etc.).

**Task 8 — Agent core + skill file loader.** Wire up the Claude Agent SDK loop (`claude_agent_sdk.ClaudeSDKClient` with `system_prompt={"type": "preset", "preset": "claude_code", "append": <skill>}` and `permission_mode="bypassPermissions"` for autonomous runs). Wrap every registered tool in an in-process MCP server via `create_sdk_mcp_server` + `@tool` decorators. Stream the SDK's tool-call events into `trace.jsonl`; surface them on stdout when `--show-reasoning` is set. Author the first version of `proteindesign.md`.

**Task 9 — SQLite persistence.** Schema migration (§6.9), `proteinclaw history`, `proteinclaw show`. CRUD tested.

**Task 10 — Pipeline orchestration & target resolution.** Implement the campaign loop: target resolution via `rcsb`/`uniprot`/`pdb`, the clarifying-question path for ambiguous targets, ESMFold→AF2-multimer cascade, top-K selection, `--rounds N` iteration. End-to-end test against a known target (PD-L1).

**Task 11 — Report generation.** `report.html` with ranking table, ESM vs AF2-multimer pLDDT scatter, 3D structure viewer (NGL or Mol*), optional reasoning panel. Single self-contained HTML file.

**Task 12 — Polish & docs.** README, install guide, troubleshooting, `proteinclaw doctor` UX, error messages. Open-sourceable surface (even if the repo stays internal).

Tasks 1–7 unblock parallel work after Task 1 lands. Task 8 depends on Tasks 2–7 for tool descriptions. Tasks 10–11 depend on 8–9.

---

## 13. Future / v2+ (explicitly deferred)

- Additional input modalities (PDB upload, UniProt ID, hotspot spec, structural constraints).
- AlphaFold DB fallback and on-the-fly target folding.
- SLURM / cloud / Kubernetes execution backends.
- Richer scoring: iPAE, Rosetta ddG, SC/SASA, self-consistency, novelty/diversity.
- Agent-driven self-iteration (reflect → relaunch) beyond `--rounds` budget.
- DNA / wet-lab protocol output.
- Multi-target project mode.
- Additional folding models (AF3, Boltz, Chai) and ligand-aware design (LigandMPNN, RFdiffusion-AA).

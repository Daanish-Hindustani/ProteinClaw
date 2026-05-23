# proteinclaw

**Agentic CLI for protein binder design.** Describe a target in plain English; get back a ranked set of binder candidates with structures, sequences, and an interactive HTML report.

> **Status:** Phase 0 — pre-implementation. The PRD, plan, and architecture are locked. No source code yet. See [PLAN.md](./PLAN.md) for the build order.

---

## What it does

`proteinclaw run "design a 60–90 residue binder to PD-L1's IgV domain"` runs this pipeline autonomously on your local GPU workstation:

```
Gemini agent  →  RFdiffusion3  →  ProteinMPNN  →  ESMFold  →  AlphaFold2-multimer
                 (backbones)      (sequences)    (pre-filter) (complex ranking)
```

The agent picks the target structure, hotspots, length range, and sampling hyperparameters from your prompt. It pre-filters non-folding designs with ESMFold (cheap, monomer), then ranks the survivors by **AF2-multimer complex pLDDT averaged over the binder chain** — the signal that actually correlates with binding.

You get back: ranked PDBs + FASTAs, an HTML report (rank table, ESM vs AF2 scatter, 3D viewer), and a full `trace.jsonl` of every agent decision.

---

## Why it exists

Binder-design pipelines are usually a stack of YAML configs, shell scripts, and manual triage. `proteinclaw` collapses that into one English sentence. The agent does the literature scan, structure fetch, epitope selection, model/hyperparam choice, execution, and triage — and logs every decision so the run is fully auditable.

**It is an internal research tool**, optimized for fast iteration on a single local GPU box. No SLURM, no cloud, no wet-lab output (yet).

---

## Hardware requirements

| | Minimum | Recommended |
|---|---|---|
| GPU | 1× NVIDIA, 24 GB VRAM (RTX 3090 / A10G / L4) | 1× A100 or H100, 40–80 GB |
| RAM | 32 GB | 64 GB |
| Disk | 200 GB free | 500 GB |
| OS | Linux + NVIDIA drivers + Docker + NVIDIA Container Toolkit | same |

At 24 GB, AF2-multimer fits for complexes <400 residues. Larger targets need 40+ GB.

---

## Install (planned)

```bash
pip install proteinclaw                # or: uv add proteinclaw
proteinclaw doctor                     # check GPU, Docker, weights, disk
proteinclaw run "design a binder to PD-L1's IgV domain"
```

`proteinclaw doctor` must pass before `proteinclaw run` is allowed. Model weights download lazily on first use into `~/.cache/{huggingface,rfdiffusion,proteinmpnn,openfold}` and persist across runs.

You need a **Gemini API key** in env (`GEMINI_API_KEY`) or `~/.proteinclaw/config.toml`.

---

## CLI surface

```bash
proteinclaw run "<prompt>" [--rounds N=2] [--max-designs N=80]
                           [--output-dir PATH] [--dry-run] [--show-reasoning]
proteinclaw history [--limit N] [--target X]
proteinclaw show <run_id>              # opens report.html
proteinclaw cancel <run_id>
proteinclaw doctor [--self-test]       # --self-test runs the full tool-level suite
```

The only mid-run interruption is when target resolution is genuinely ambiguous (multiple isoforms / unrelated PDB structures) — the agent asks **one** clarifying question with a numbered menu. Otherwise it proceeds on best-guess and logs every assumption.

---

## What's in the box

```
runs/<run_id>/
  designs/
    rank_01_<id>.pdb
    rank_01_<id>.fasta
    ...
  report.html              # interactive: rank table, pLDDT scatter, 3D viewer
  plan.md                  # agent's initial plan
  trace.jsonl              # every prompt, tool call, decision, error
  literature.md            # papers / web findings the agent used
  config/                  # configs the agent generated per stage
  raw/                     # raw model outputs (reproducibility)
```

Plus a row in `~/.proteinclaw/runs.db` (SQLite).

---

## Architecture in one paragraph

A Gemini agent runs inside a **RestrictedPython sandbox** for parsing and glue, and dispatches GPU-heavy models out to **local Docker containers** via a `ComputeRouter` → `LocalRunner` chain. Every model tool follows a strict **4-file convention** (`tool.yaml`, `Dockerfile`, `implementation.py`, `tool_entrypoint.py`) — adding a new model is one directory, no other edits. Tools share state through a per-run **session workspace** mounted at `/workspace` in every container, and pass *paths* (never multi-MB PDB bytes) through the LLM context.

Full details in [ARCHITECTURE.md](./ARCHITECTURE.md). Normative spec in [PRD-proteinclaw.md](./PRD-proteinclaw.md) §9.

---

## Project docs

| Doc | Purpose |
|---|---|
| [PRD-proteinclaw.md](./PRD-proteinclaw.md) | Normative spec (v1.0.0). When other docs disagree, the PRD wins. |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | How the pieces fit together and why. |
| [PLAN.md](./PLAN.md) | Modular task breakdown — implementation, tests, success criteria, manual test per task. |
| [SETUP.md](./SETUP.md) | Lambda Labs VM setup for development (A100, persistent FS, Claude Code over SSH+tmux). |
| [NOTES.md](./NOTES.md) | Append-only cross-session engineering notebook — fixes, gotchas, pinned versions. |
| [CLAUDE.md](./CLAUDE.md) | Guidance for Claude Code when working in this repo. |

---

## Design principles (load-bearing)

- **Fail fast and loud.** No silent fallbacks to degraded pipelines. Three deliberate graceful-degradation paths exist (literature rate-limit, web scrape failure, ColabFold timeout → single-sequence MSA) and they all log loudly.
- **Rank by the complex, not the monomer.** AF2-multimer complex pLDDT over the binder chain is the ranking signal. ESMFold is a cheap pre-filter only.
- **Paths, not bytes.** PDBs never cross the LLM context. Tools write to `/workspace/<tool>_<step>/` and return paths.
- **The skill file is the agent.** `proteinclaw/skills/proteindesign.md` is concatenated into the system prompt every run. Edit it to change agent behavior without touching code.
- **One directory per model.** No edits to the registry, router, or agent when adding a new tool.
- **The trace is the reproducibility artifact.** No `--seed` flag — Gemini's plans are non-deterministic by design. `trace.jsonl` is what you keep.

---

## Status & roadmap

**v1 (in progress):** the pipeline above, single local GPU, natural-language input only, AF2 complex pLDDT as the sole ranking signal.

**Explicitly deferred to v2+:** additional input modalities (PDB upload, UniProt ID, hotspot spec), AlphaFold DB target fallback, SLURM / cloud backends, richer scoring (iPAE, ddG, SC/SASA), self-iteration beyond `--rounds`, DNA / wet-lab output, AF3 / Boltz / Chai, LigandMPNN, RFdiffusion-AA.

See [PRD-proteinclaw.md §13](./PRD-proteinclaw.md) for the full deferral list.

---

## License

TBD (internal tool for now).

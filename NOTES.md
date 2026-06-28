# NOTES.md — Cross-session Engineering Notebook

**Purpose:** persistent log of fixes, gotchas, pinned versions, and decisions the
next session needs that are not already obvious from PRD / ARCHITECTURE / PLAN /
README / CLAUDE / git history.

**Convention:** append-only between owner-directed compactions. The repo owner
may periodically compact this file; full history remains in git.

> **Compacted 2026-06-28** after the agent-native MCP refactor. Removed verbose
> one-off run logs, superseded Hermes-primary notes, and stale historical
> wording. Kept durable environment, tool-wrapper, workflow, and architecture
> footguns.

---

## Current Architecture

- ProteinClaw is now Codex/Claude-native. The primary runtime is
  `proteinclaw mcp serve`.
- Codex/Claude own the model loop, native web research, critique, and
  subagents/tasks.
- ProteinClaw MCP exposes domain-specific tools only: run lifecycle, target
  helpers, PubMed/literature helpers, RFdiffusion3, ProteinMPNN, ESMFold,
  AF2-multimer, interface metrics, run artifacts, scoped skill append/create,
  and report generation.
- ProteinClaw MCP intentionally does **not** expose generic web search or generic
  subagent tools. If a skill or doc says to use `research_scout` in the
  Codex/Claude path, it is stale.
- Codex install files live at `.codex-plugin/plugin.json`, `.mcp.json`, and
  `codex-skills/proteinclaw-workflow/SKILL.md`.
- Claude Code uses the same MCP command directly:
  `uv run --project . proteinclaw mcp serve`.

## Environment

- Bare Ubuntu 24.04 Lambda VMs may have no NVIDIA driver, Docker, or NVIDIA
  Container Toolkit. Install in order: driver → `modprobe nvidia nvidia_uvm
  nvidia_drm` → Docker → NVIDIA Container Toolkit → Docker restart.
- `usermod -aG docker` does not affect the current shell. Use a fresh login or
  wrap commands with `sg docker -c '...'`.
- Wire persistent cache symlinks before any model download:
  `~/.cache/{huggingface,rfdiffusion,proteinmpnn,openfold}` and
  `~/.proteinclaw` should point at the persistent filesystem.
- A10 cards report about 23028 MiB, so integer VRAM is 22 GB. Do not lower the
  global 22 GB floor; OOM fixes are smaller targets, shorter binders, or fewer
  recycles.
- `prodigy-prot` / `freesasa` builds need Python dev headers, e.g.
  `python3.12-dev`.

## Tool Wrapper Rules

- GPU model tools use the 4-file convention: `tool.yaml`, `Dockerfile`,
  `implementation.py`, `tool_entrypoint.py`. `_normalize.py` is the allowed fifth
  file for host-side tests.
- `tool.yaml` schemas must stay flat for agent compatibility: no `allOf`,
  `oneOf`, `anyOf`, `if`, `then`, or `else`. Enforce mode-dependent validation in
  normalization/runtime code.
- GPU images bake wrapper code with Docker `COPY`; after editing wrapper code,
  delete/rebuild the image. `_ensure_image` only builds when the image is
  missing.
- Containers run as host UID/GID and mount caches at `/cache/<name>`, not
  `/root/.cache`.
- Tools should pass paths, not PDB bytes. Containers see `/workspace`; host-side
  tool envelopes may contain translated host paths.

## Model-Specific Notes

- RFdiffusion3 partial diffusion uses `partial_t` in Angstroms of noise, not the
  old RFdiffusion `partial_T` timestep count. RFD3 caps `partial_t <= 15`.
- ProteinMPNN soluble weights exist for all four bundled models in the actual
  image, despite stale upstream README wording. `use_soluble_model` can be used
  with any allowed model.
- ESMFold uses `facebook/esmfold_v1`; the image pins torch 2.6+ because older
  torch refuses `from_pretrained` after CVE-2025-32434.
- AF2-multimer uses ColabFold/JAX pins that require cuDNN 8. CUDA 12.4 cuDNN 9
  images break JAX 0.4.23.
- ipSAE metrics are derived from Dunbrack `ipsae.py`, not native ColabFold
  fields. Scorer failure should soft-fail with `ipsae=null`, leaving the
  structure usable.

## Workflow and Quality Gates

- Mini-binder ranking signal is AF2-multimer complex pLDDT over the binder
  chain. ESMFold monomer pLDDT is only a pre-filter.
- Mini-binder hit gate is strict AND: complex pLDDT, ipSAE, ipTM, hotspot
  satisfaction, and BSA must all clear thresholds. Missing metrics fail.
- Nanobody workflow does not use RFdiffusion3 or ProteinMPNN. It generates VHH
  libraries and scores nanobody-target complexes.
- For GPCR nanobody targets, crop to the extracellular face. Feeding the full
  7-TM receptor to AF2-multimer causes membrane-in-vacuum artifacts: huge BSA,
  high clash, and non-physical interpenetrating poses.
- Nanobody gate includes two-sided BSA and clash guards. PRODIGY KD is advisory
  only and is unreliable for high-clash / over-large-BSA poses.

## Data and Triage

- `data.pdb_fetch` can count waters/HETATM as chain residues. Verify true
  protein span from `ATOM` records before cropping.
- RCSB search returns `result_set`; resolution/date/method require a second
  Data API call.
- LitSense/PubMed rate limits are expected degradation. A 429 should return a
  rate-limited envelope, not crash the run.
- `trace.jsonl` is the reproducibility artifact. Triage parses tool envelopes
  from trace; large envelopes must stay under the trace trim cap or get a side
  channel.

## Security

- Codex/Claude may have host shell access. ProteinClaw MCP itself is narrower,
  but prompt-injection risk still exists through the host agent's native tools.
- The right isolation boundary is a dedicated/disposable VM with no unrelated
  standing secrets. In-process Python sandboxing is not a meaningful control
  beside host shell access.

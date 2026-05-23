# Example run — PD-L1 IgV binder, colabfold MSA

Reference output from `proteinclaw run` against a real GPU. Used as a
fixture for documentation + UI demos.

## What this is

A full end-to-end campaign:

```
proteinclaw run --skip-doctor --max-turns 80 -o /tmp/proteinclaw-fullE2E-colab2 \
  "Design a 60-70 residue binder to PD-L1 IgV domain. Use the canonical 8-step
   pipeline. For RFD3 generate num_designs=2. For MPNN use num_sequences=2 per
   backbone. For AF2-multimer use msa_source=colabfold (the real ranking
   signal). Use ESMFold threshold 65. Per the skill file: call data.pdb_fetch
   first with only pdb_id, then again with chain=A to see gap info, and pick a
   crop range that does NOT span any gap. Rank by AF2 complex_confidence and
   report the top 1-2 designs."
```

## What ran

- **Target**: PDB **6NM7** chain A crop 19-127 (PD-L1 IgV domain V76T, 1.92 Å).
  The agent inspected chains first via `data.pdb_fetch(pdb_id="6NM7")`, then
  fetched chain A with gap info to pick a crop that avoided unmodeled loops
  (the `_normalize.py` fix that prevents the `Residue A45 not found` failure
  mode seen on 6NP9 earlier).
- **Hotspots**: `A56, A115, A123` — canonical PD-L1/PD-1 interface residues.
- **Backbones**: 2 from RFdiffusion3 (binder on chain A per the new
  envelope-reported `output_binder_chain`, target on chain B).
- **Sequences**: 2 ProteinMPNN sequences per backbone (4 total).
- **ESM pre-filter**: threshold 65 — all 4 sequences passed.
- **AF2-multimer**: 4 calls with `msa_source=colabfold` (real paired MSA from
  the MMseqs2 server) — each used a unique jobname-hash to avoid the
  ColabFold skip-on-exist cache collision we hit earlier.

## Ranked designs

| rank | AF2 complex pLDDT | ESM monomer | length | binder sequence prefix |
|---:|---:|---:|---:|---|
| 1 | **79.65** | 67.5 | 66 aa | `LTGTFS...` |
| 2 | 75.06 | 75.6 | 66 aa | `LTGTFS...` |
| 3 | 73.10 | 72.1 | 66 aa | `FERAAE...` |
| 4 | 64.13 | 74.1 | 66 aa | `FEKAAE...` |

All four designs are non-degraded (paired MSA worked on all four calls).

The rank-1 design at **79.65** is right at the edge of the "experimentally-
validated hit" gate in the literature (Bennett et al. 2023 *Nat Commun*:
complex pLDDT > 80 + pae_interaction < 10). For a tiny 2-backbone exploration
this is a genuinely promising starting point — a serious campaign would
re-rank these with `num_models=5` AF2 and then run a follow-up round with
partial diffusion seeded on the rank-1 backbone.

## Run cost / time

- **Wall time**: ~25 min on one A100 40GB
- **Subscription credit**: ~$1.30 (rough Agent SDK billing estimate; check
  your Claude.ai usage page for the exact number)
- **Turns**: 13 (mostly tool calls; the agent didn't need built-ins for this
  run since the gap-detection fix surfaced the info it needed)

## Files

```
.
├── README.md           # this file
├── result.json         # canonical machine-readable run record
├── report.html         # self-contained UI (open in any browser)
├── trace.jsonl         # full agent event log — every tool call + assistant text
└── designs/
    ├── rank_01_LTGTFS.pdb
    ├── rank_02_LTGTFS.pdb
    ├── rank_03_FERAAE.pdb
    └── rank_04_FEKAAE.pdb
```

`report.html` is **self-contained** — open it directly in any browser. The
Mol* viewer pulls from cdn.jsdelivr.net (cached after first load); the rank
table, scatter plot, and pipeline summary are all inline.

## How to reproduce

You need: an A100-class GPU, Docker, all four model images built
(`proteinclaw/{proteinmpnn,esmfold,rfdiffusion3,af2multimer}:0.1.0`),
Claude Code installed + logged in (subscription path; `ANTHROPIC_API_KEY`
must be unset), and `proteinclaw doctor` green.

```bash
proteinclaw run \
  -o ./runs \
  --max-turns 80 \
  "Design a 60-70 residue binder to PD-L1 IgV domain. Use msa_source=colabfold."
```

Output lands under `./runs/<run_id>/`. Open `report.html` to inspect.

The exact sequences and pLDDT values in this example will not reproduce
bit-identically — the agent's plan is non-deterministic (PRD §7: trace is the
reproducibility artefact, not a seed), and ColabFold + AF2 sampling is also
non-deterministic. Order-of-magnitude metrics (complex pLDDT ~70-80 for a
clean PD-L1 IgV target) will reproduce.

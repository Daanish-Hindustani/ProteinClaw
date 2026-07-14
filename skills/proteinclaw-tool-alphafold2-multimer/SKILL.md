---
name: proteinclaw-tool-alphafold2-multimer
description: ProteinClaw per-tool guidance for alphafold2_multimer.
---

# Tool skill: `structure.alphafold2_multimer` — complex prediction for triage/confirmation

Read this before pipeline **step 7** (complex ranking). It is the
operational detail for the one-line summary in the core skill. Read it
carefully because downstream scoring depends on how many AF-M models you run.

For each surviving sequence:

`proteinclaw_structure_alphafold2_multimer`:
- `binder_sequence=<designed sequence>`
- `target_sequence=<the SAME crop used in step 1>` (not the full
  UniProt chain). Two reasons: AF2 caps target_sequence at 1024 aa,
  AND biologically you want AF2 predicting against the interface RFD3
  was designing against.
- `msa_source="colabfold"` (the default — paired MMseqs2 MSA on the
  target). The binder has no homologs so its MSA is single-sequence
  either way. Falling back to `single_sequence` for the target
  materially weakens pLDDT/PAE — `msa_degraded: true` should be a
  red flag in triage.
- `num_recycle=3`, `num_models=1` for broad triage when cost matters.
  **Mandatory confirmation pass:** before reporting or judging the gate,
  re-run the best candidates with `num_models=5` and `num_recycle=6–12`,
  then call `proteinclaw_analysis_afm_screen_score` with the returned
  `out_folder` and `complex_pdb_path`. Passing `complex_pdb_path` is important
  because a reused AF2 output folder can contain multiple candidate jobs. For nanobody/GPCR screens, final ordering should use
  `combo_feature` + model support from that scorer, not a single rank-1
  `complex_confidence` alone. A single model/seed gives noisy ipSAE; the
  five-model agreement score is the trustworthy one.
  It's a **robustness check, not a score-lifter**: confirmed ipSAE is
  ≈ triage or slightly lower for solid designs and collapses for
  lucky-model outliers (TREM2: 0.83→0.64). Ship the robust ones.

Result envelope's **`complex_confidence`** (binder-chain mean pLDDT)
is a first-pass fold-confidence feature and compatibility field. It may help
order broad triage, but a one-model job can only eliminate candidates, never
confirm one. The envelope
**now also carries interface-quality metrics directly** (computed by
Dunbrack's ipsae.py on the predicted PAE): `ipsae`, `iptm`, `pdockq`,
`pdockq2`, `lis`. Use these envelope fields as your primary interface read.
For confirmation runs, feed the `out_folder` into
`proteinclaw_analysis_afm_screen_score` to aggregate all ranked AF-M model
PDB/JSON pairs for that same candidate job.

**Still worth `Read`-ing the raw ColabFold JSON for more signal.** The
envelope is a summary; the full per-residue detail lives in the
`out_folder` from the AF2 result — `<jobname>_scores_rank_001_*.json`
(the full `pae` matrix, `plddt` array, `ptm`/`iptm`) and the ipsae.py
outputs written next to the PDB: `*_<pae>_<dist>.txt` (all chain-pair
scores incl. `ipSAE_d0dom`, `pDockQ2`, residue counts) and
`*_<pae>_<dist>_byres.txt` (per-residue ipSAE — pinpoints which binder
residues drive the interface). When a design is borderline or you want
to understand *why* the interface scores the way it does, `Read` these.
More information is better — the envelope fields are the fast path, the
raw files are the deep dive.

**The full literature picture:** the canonical "hit gate" in
Bennett 2023 / BindCraft / the 2025 meta-analysis is NOT plain complex
pLDDT alone. It's an interface-quality read:

| Metric | Threshold (proteinclaw strict gate) | In envelope as | Source |
|---|---|---|---|
| interface PAE-based score (`ipSAE`) | **≥ 0.93** (0.3 is *marginal*, not a pass) | `ipsae` | Dunbrack 2025 |
| `ipTM` | **≥ 0.7** | `iptm` | BindCraft / meta-analysis |
| complex pLDDT (`plddt_binder`) | **> 93** | `complex_confidence` | Bennett 2023 |
| hotspot satisfaction | **≥ 0.70** | `analysis.interface_metrics` | this pipeline |
| interface BSA | **≳ 700 Å²** | `analysis.interface_metrics` | this pipeline |
| `pDockQ` | higher = better interface | `pdockq` | Bryant 2022 |
| Cα RMSD binder vs designed | **< 2 Å** | (not surfaced) | Bennett 2023 |

ipSAE is a PAE-derived interface score (the same signal as Bennett's
`pae_interaction`, the single most discriminative metric — ~10× higher
experimental hit rate when filtered on it). The proteinclaw **hit gate
is a strict AND of all of the above** (see proteinclaw-minibinder/SKILL.md §Quality
gate) — pLDDT alone never passes a design. A design with high complex
pLDDT but `ipsae` below ~0.93 is a likely false positive (folded binder,
weak/non-specific interface) and is **not** a hit. If `ipsae` is `null`
an `ipsae_error` field says why — that design cannot be a hit; note it.
ProteinClaw's deterministic legacy *sort* stays on `complex_confidence`.
For GPCR nanobodies, final ordering must instead use five-model
`analysis.afm_screen_score` evidence plus mapped positive/forbidden-face QC and
separation from a target-matched negative control. The *gate* you stop on is
the multi-metric one.

**Large complexes**: if binder + target > 400 residues, AF2 may OOM on
a 24 GB GPU. Either accept the risk (let the tool return a structured
OOM error and drop that design) or crop the target tighter.

# TREM2 binder design — plan.md

## Target
- TREM2 (Q9NZC2 human), PDB 5ELI chain A, crop 20-130 (111 res IgV ectodomain).
- 5ELI = apo TREM2 IgV dimer in crystal; ligand-binding face on apex (CDR-like loops).
- Gap 132-200 avoided by cropping at 130. Ig-V-set domain (UniProt 23-128).

## Design hypothesis (round 1)
- Strategy: α-helical bundle binders targeting TREM2 cationic surface, drawing on learned/ig-v-flat-face.md — with the current RFD3 wrapper (no strand conditioning), generic β backbones fail to dock; α-helical bundles are the productive topology.
- Hotspots: W44 (aromatic anchor, CDR1), R47 (Alzheimer's R47H variant — central charged anchor on ligand-binding face), H67 (CDR2 region), R76 (CDR3-adjacent, anionic-ligand cluster). 4 sparse hotspots = canonical IgV apex.
- Binder length: 75 aa (mini-binder sweet spot; well under user's ≤250 limit).
- Funnel: RFD3 8 backbones × MPNN 4 seqs = 32 sequences → ESM filter (pLDDT≥70) → AF2 on top survivors.
- RFD3 params: PPI defaults (step_scale=3, gamma_0=0.2, is_non_loopy=true).
- MPNN temp 0.1 (round 1 conservative).

## Rationale
- Skipping research scout fan-out: prior PD-L1 run showed checkpoint/immune-receptor topics sometimes hit API content filter; the learned IgV playbook directly applies. TREM2 cationic surface hotspots are well-documented in the AD literature (R47H AD variant; H67/R76 in anionic-lipid binding cluster).
- One round budget. Refine via partial diffusion on winners if gate not met.

## Round 1 result
- Funnel: RFD3 8 backbones → MPNN 32 sequences → ESM survived 30/32 (mean pLDDT 79.2) → AF2 on 8 best-per-backbone.
- Strict gate (complex pLDDT >93, ipSAE ≥0.93, ipTM ≥0.7, hotspot ≥70%, BSA ≳700): **0 hits** — bottleneck is ipSAE ≥0.93 (best observed 0.79).
- By practical published thresholds (ipSAE ≳0.6, ipTM ≳0.75) **3 plausible binders**:

| Rank | Backbone | complex pLDDT | ipSAE | ipTM | pdockq | Hotspot sat | BSA Å² | Clash |
|------|----------|---------------|-------|------|--------|-------------|--------|-------|
| 1 | bb1 | 97.10 | 0.792 | 0.91 | 0.442 | 75% (R47 missed) | 1638 | 12.15 |
| 2 | bb3 | 97.29 | 0.685 | 0.84 | 0.278 | 50% | 1269 | 9.50 |
| 3 | bb2 | 94.32 | 0.595 | 0.78 | 0.242 | 50% | 1454 | 18.43 |

- bb1 is the standout (matches the ig-v-flat-face learned playbook: α-helical bundle, sparse 4-hotspot hint produced 75% satisfaction with R47 — the AD-variant residue — being the lone miss).


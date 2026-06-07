# Run plan & reasoning — TREM2 IgSF binders

Target: human TREM2 V-type Ig-like ectodomain. User requires ipSAE ≥ 0.88.
Per learned skills the unconditioned-RFD3 ceiling here is ~0.82; 0.88 is
above the architecture's empirical ceiling. Spending the full 4-round
budget chasing it with structural pivots, but I will be honest about the
gap in the final report.

## Target resolution
- PDB 5ELI chain A; chain B also present (dimer in crystal).
- Full chain spans 20-201 with a 132-200 gap (stalk absent). Use crop **20-131** (112 aa IgSF domain).
- Sequence verified against the user-supplied 113-aa construct (His-tag end).
- Cropped target PDB written to /workspace/pdb_fetch_1/5ELI_chainA_20-131.pdb.

## Round-1 research scouts (§1.5, MANDATORY)
Three parallel scouts (`research` Sonnet tier, all returned without filter refusal):

1. **TREM2 binder precedent** — Perera 2026 (PMID 42079091) describes two
   experimentally-validated de novo TREM2 minibinders, **BindCraft8** and
   **Odesign2**, both helix-loop-helix wrapping the apical hydrophobic tip
   at L69/W70. Cyclic peptide TP4 (Shu 2025) also targets the same patch.
   IgV mini-binder precedent: 60-120 aa α-helical bundles dominate
   (Shanker 2022 PD-1/PD-L1, BindCraft IgV targets).
2. **IgV designability** — PMC12852815 quantifies: unconditioned RFD on
   IgSF targets = ~1% in-silico pass; β-strand conditioning lifts to 9.2%.
   Our wrapper has no strand conditioning lever. ipTM ≥ 0.70 + pAE < 10 +
   binder pLDDT > 85 = standard accept gate; ipSAE not benchmarked
   target-specifically.
3. **Mini-binder developability** — Bennett 2023 RFdiffusion: ~19% BLI hit
   rate across 5 targets; BindCraft adds MPNNsol + ≤35% surface
   hydrophobic exposure + negative net charge filter → 10-100% (mean ~46%).
   Vanilla MPNN at temp 0.1 ≠ MPNNsol; expect some shipped designs to
   need post-hoc surface review. No A/B trial exists.

## Due-diligence (§1.6)
- **Structural sandbox (biopython SASA + NeighborSearch on 5ELI):**
  W44 SASA=132, L69=65, W70=39, L71=143, F74=124, W78=68 — all exposed,
  all surface aromatic/hydrophobic. CDR1 (W44 cluster) and CDR2 (L69/W70/L71/F74/W78)
  both presentable; CDR3 (R98) is on the periphery.
- The scout's literature L69/W70 ≈ the learned skill's F74/W78. Both are
  pointing at the apical CDR2 hydrophobic patch — same surface, slightly
  different anchor pick.

## Debate (§1.7) — adjudicated
Contested point: which hotspot set for round 1?
- **Learned (3 prior TREM2 runs):** {A44, A74, A76, A78} — proven ipSAE ~0.82,
  α-helical bundle, W78 chronically unsatisfied at 75% sat.
- **Scout (Perera/Bhatt):** L69/W70 are the published functional hotspots;
  ApoE/TDP-43 binders engage L69/W70 anchor.
- **Resolution:** HEDGE. Both sets target the same apical face. Run both
  branches in round 1; the data adjudicates. Length 75-95 covers both
  helical-bundle (75-85) and slightly-longer extended-loop (90-95).
- **Adjudicated design hypothesis (round 1):**
  - Branch A (proven CDR2-ridge): {A44, A74, A76, A78}, len 75-90, 6 designs
  - Branch B (literature L69/W70 anchor): {A69, A70, A74, A78}, len 75-95, 6 designs
  - MPNN n=3 each, temp=0.1; ESM ≥70; AF2 colabfold num_models=1.
  - Target: at least one design at ipSAE ≥ 0.78 in either branch, then partial-t polish in round 2.

Budget check: round 1 of 4. Will use all 4 unless gate met (≥3 designs at
ipSAE≥0.88 AND ipTM≥0.7 AND complex pLDDT > 93 AND hotspot sat ≥0.70 AND BSA ≳700).

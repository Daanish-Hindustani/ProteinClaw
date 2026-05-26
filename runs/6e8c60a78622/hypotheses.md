# TREM2 binder campaign — hypotheses log

Target prompt: design a binder to TREM2 (PDB 5ELI), sequence ≤ 250 aa.

## Target resolution
- UniProt **Q9NZC2** (human TREM2, 230 aa); Ig-like V-set domain res 29–112.
- PDB **5ELI** (Kober et al. eLife 2016, apo TREM2 ectodomain). Chains A & B both = res 20–201 with one large gap (132–200 unmodeled). Modeled continuously 20–131.
- **Crop chosen: chain A, 20–131** (112 res, gap-free, hosts full Ig V-set domain).
  Host path: `/home/ubuntu/.proteinclaw/gpu-workspace/6e8c60a78622/pdb_fetch_0/5ELI_chainA_crop20-131.pdb`
- 5ELI is *apo* → no co-crystal interface; hotspots from literature + structural sandbox.

## Round 1

### Scout hypotheses (§1.5)
- **S1 (prior campaigns):** target DISTAL β-sandwich hydrophobic face (V23,P102,L107,L125,V128,A130,E127) where anti-TREM2 scFvs bound **sub-nM** with SOLVED co-crystals (PMC8575122). Avoid basic patch (ligand competition, R47H isoform issues). conf med.
- **S2 (ligand surface):** target apical CDR / basic patch (R47,R62,R76,R77,L69,W70) — functional ligand-binding hotspot. conf med-high.
- **S3 (Ig-fold designability):** flat β-faces favor β-strand-augmented binders (β-pairing RFdiffusion, Sappington 2026 PMC12852815); pure helical bundles weaker on flat β. Length 60–100. conf med-high.
- **S4 (length/thresholds):** length 65–80 aa, 4–6 hotspots, AF2 PAE_int<8 & pLDDT>85 & ipTM≥0.7. conf med.

### Due diligence (§1.6) — my structural sandbox on 5ELI crop (Shrake-Rupley SASA)
- DISTAL set all solvent-exposed (RSA 0.28–0.57); hydrophobic members V23,L107,L125,V128,A130,L129.
- BASIC patch = **four arginines** R47/R62/R76/R77 (polar) + **W70 BURIED (RSA 0.14)** → low-designability polar surface.
- Tightest concave hydrophobic sub-cluster: **V23–L107–L125** (CB dists 4.5–9.9 Å), extending to **V128** (max pairwise within the 4 = 13.2 Å). = exactly the scFv-4 contact set.

### Debate log (§1.7)
- **Contested: epitope (S1 distal vs S2 basic).** Challenged S2 with: 4-Arg polar patch + W70 buried + RFdiffusion polar-site caveat + scFv co-crystal at distal face + user wants "a binder" (no functional req). → **S2 REVISED/conceded (high conf): distal face wins.** Decisive evidence: PMID 37433327 polar-site caveat, PMC8092486 hydrophobic-patch principle, PMC8575122 sub-nM co-crystal.
- **Contested: topology (S3 β-pairing requirement).** Challenged with: epitope is a CONCAVE groove not a flat edge strand; tool = standard RFD3 (no β-pairing mode). → **S3 REVISED/conceded (med conf): standard helical/mixed RFD3 PPI-mode OK for concave pocket** (Keap1 pocket precedent PMC11928978; Dang 2017 PMID 28082595). Flags: size >70 aa for loop reach; `is_non_loopy=false` is a round-2 lever.

### CHOSEN DESIGN HYPOTHESIS (round 1)
- Epitope: distal β-sandwich concave hydrophobic groove.
- **Hotspots: A23, A107, A125, A128** (V23,L107,L125,V128). Side-chain atoms (Val: CB,CG1 / Leu: CG,CD1).
- **Binder length: 70–90 aa** (>70 for groove loop reach; within 60–80 consensus; ≤250 cap satisfied).
- RFD3: num_designs=8, num_timesteps=50, step_scale=3, gamma_0=0.2, is_non_loopy=true.
- MPNN: temp 0.1, num_sequences=4 (→ 32 AF2 jobs).
- ESMFold triage cut: confidence ≥ 70.
- AF2: colabfold MSA, num_recycle=3, num_models=1. Gate: ≥5 designs complex_confidence>75 (& ipsae≳0.3).
- Wall-time flag: 32 AF2 complexes ≈ 4–5 h on one A100.

### Round 1 budget check: cycle 1 of (no hard cap). Funnel 8×4=32. Round-2 levers held in reserve: partial diffusion on winners, is_non_loopy=false, narrow length.

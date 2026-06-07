# TREM2 binder design — plan.md

## Target resolution
- PDB 5ELI chain A, crop 20-131 (Ig V-set ectodomain; gap 132-200 = stalk, omitted).
- UniProt Q9NZC2 (human TREM2), 230 aa, Ig-V-set domain 29-112.
- Cropped PDB: `/home/ubuntu/.proteinclaw/gpu-workspace/c65c38531279/pdb_fetch_1/5ELI_chainA_crop20-131.pdb`

## Round 1 hypothesis
**Evidence:**
- Learned IgV skill (PD-L1 run f1c91f9...): α-helical bundle binders dominate flat Ig-V
  faces; 4 sparse aromatic/hydrophobic + 1 charged hotspot → 100% hotspot satisfaction.
  Generic β backbones fold but fail to dock (no strand conditioning in our wrapper).
- PubMed PMID 40280075 (Dantas 2025): TREM2 protein recognition mediated by CDR2 region.
- SASA + spatial check on 5ELI/A: CDR2 patch F74/L75/R77/W78 forms tight ~10 Å exposed
  cluster — 2 aromatics + hydrophobic + charged centering. Pairwise max 9.9 Å.
- W44/M41 are far from CDR2 cluster (>13 Å) → excluded (would over-spread the patch).

**Design choice (round 1):**
- hotspots = `A74,A75,A77,A78` (F74 L75 R77 W78), default CA/CB atoms.
- binder_length = 70-90 (mini-binder canonical for α-helical bundle).
- RFD3 num_designs = 12, PPI canon (step_scale=3, gamma_0=0.2, is_non_loopy=true).
- MPNN num_sequences = 3 @ temp=0.1 → 36 sequences.
- ESM pLDDT ≥ 70 cutoff → AF2 multimer (colabfold MSA, num_models=1).
- Strict quality gate: complex pLDDT >93, ipSAE ≥0.93, ipTM ≥0.7, hotspot ≥0.70, BSA ≳700 Å².

Budget cap: 4 rounds total. Rounds 2-4 reserved for partial-diffusion on round-1 winners
if gate unmet.

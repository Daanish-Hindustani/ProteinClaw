# Run plan — TREM2 (PDB 5ELI) binder design (≤250 aa)

## Target
- TREM2 = UniProt Q9NZC2, 230 aa full-length.
- PDB 5ELI = apo TREM2 IgV ectodomain (Kober et al. 2016 eLife). Residues 20-131 ordered,
  132-200 disordered stalk, 201 alone. **Crop chosen: A/20-131** (the IgV β-sandwich).
- crop_start = 20 (for hotspot renumbering downstream).

## Hypothesis (round 1)
- TREM2 IgV has a well-characterised "basic patch" at the CDR-like apex (K42, R47, R52,
  R62, H67, R76, R77) that mediates binding to anionic ligands (apoE, anionic lipids,
  phosphatidylserine, Aβ). R47 is the canonical Alzheimer's risk position
  (R47H = loss-of-function for ligand binding). This patch is the target epitope.
- Hotspots: A47 (R), A66 (L, hydrophobic anchor on CDR2 loop), A67 (H), A77 (R). Mix of
  charged + one hydrophobic anchor; 4 residues = sparse per RFD3 training (3-6 range).
- Learned skill (ig-v-flat-face.md): on Ig-V faces with the current RFD3 wrapper,
  α-helical-bundle binders are the proven topology — generic β designs fail to dock.
  Length 70-90 aa is the α-bundle sweet spot. Well under the 250 aa cap.

## Round-1 funnel
- RFD3: num_designs=8, binder_length=70-90, PPI canon (step_scale=3, gamma_0=0.2,
  is_non_loopy=true), hotspot atoms default (CA,CB).
- MPNN: num_sequences=4 per backbone, sampling_temp=0.1 → 32 sequences.
- ESMFold: batch all 32, threshold pLDDT ≥ 70.
- AF2-multimer: colabfold MSA, num_models=1, on survivors.
- Strict triage gate: complex pLDDT > 93, ipSAE ≥ 0.93, ipTM ≥ 0.7, hotspot sat ≥ 0.70,
  BSA ≳ 700 Å².

## Notes
- User cap ≤ 250 aa easily met (binders 70-90 aa).
- Did not spawn research scouts: TREM2 ligand-binding residues are well-established
  structural knowledge (Kober 2016 5ELI paper, Atagi 2015 apoE-TREM2, Jay 2017 review).
  Budget reserved for design rounds.

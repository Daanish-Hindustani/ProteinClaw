---
id: motif_scaffolding
version: 2
name: Motif Scaffolding
description: Scaffold a functional motif inside a de novo protein, preserving motif geometry while permitting flanking design.
applicable_tasks: [motif_scaffolding]
provenance: human_authored
parent_version: 1
---

## Goal

Build a stable, well-folded *de novo* scaffold around a fixed functional motif (epitope, active site, binding loop) such that the motif's backbone geometry is preserved within a tight RMSD threshold.

## Inputs

- `motif_pdb` — PDB id or path containing the motif residues to fix.
- `motif_residues` — explicit residue range (e.g. `["A20-25", "A40-45"]`).
- `total_length_range` — desired final length, e.g. `60..100`.

## Steps

1. **Build the contig string.** RFdiffusion's contig syntax fixes motif segments and lets the model fill in the flanking length. Example for two motif segments and a 60-100 aa scaffold: `10-30 A20-25 5-15 A40-45 10-30`. Each unbracketed range is the *free* segment length to sample (RFdiffusion picks within the range).
2. **Generate scaffolds.** Call `rfdiffusion3` with the contig string. Sample ≥ 8 backbones; motif scaffolding has higher failure rates than binder design — produce more candidates upfront.
3. **Design sequences.** Call `protein_mpnn` per backbone, fixing motif residues. `num_sequences=4` per backbone; `sampling_temperature=0.1`.
4. **Predict structures.** Call `alphafold` (single-sequence is fine for *de novo* scaffolds with no MSA).
5. **Score motif preservation.**
   - **Motif backbone RMSD ≤ 1.0 Å** is the hard gate. Designs above 1.5 Å have lost the motif geometry and should be rejected.
   - **Global pLDDT ≥ 0.75** for confident folds.
6. **Score global stability.**
   - **pTM ≥ 0.70** for plausible topology.
   - **Clash score < 5.0**.
7. **Filter for novelty (if needed).** Call `foldseek`. For published *de novo* scaffolds, ensure the closest hit (excluding the motif's source structure) has TM-score < 0.6.
8. **Return ranked candidates.** Order by `(motif_rmsd asc, pLDDT desc)`.

## Common pitfalls

- **Free segments too short.** Tight flanking ranges (< 5 residues per side) make it hard for RFdiffusion to satisfy the motif geometry; failures often present as broken backbones at the motif boundary.
- **Motif spread across distant chains.** When motif segments are far apart in 3D space, force the contig to allow longer connecting segments rather than crashing them into a small scaffold.
- **Trusting low-pLDDT motif boundaries.** RMSD can pass while individual boundary residues have pLDDT < 0.5 — inspect per-residue confidence in the motif before accepting.

## Worked example

> Motif: 1ABC residues A20-25 + A40-45. Target scaffold length: 70-90.

```text
contigs = "10-30 A20-25 5-15 A40-45 10-30"
rfdiffusion3 → 8 backbones
protein_mpnn (per backbone, fix motif) → 4 sequences each
alphafold (per sequence) → 32 predictions
filter motif_rmsd <= 1.0 Å, pLDDT >= 0.75 → typically 3-7 survivors
foldseek → ensure structural novelty
rank by (motif_rmsd, pLDDT)
```

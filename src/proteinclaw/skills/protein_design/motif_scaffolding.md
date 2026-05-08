---
id: motif_scaffolding
version: 1
name: Motif Scaffolding
description: Build a protein scaffold around a fixed functional motif.
applicable_tasks: [motif_scaffolding]
provenance: human_authored
parent_version: null
---

> Phase 3 placeholder. Real workflow content authored in Phase 6.

## Inputs

- Motif PDB fragment with the residues to preserve.
- Desired total length range.

## Steps

1. Construct a contig string fixing the motif residues.
2. Generate scaffolds with `rfdiffusion3` using the contig.
3. Design sequences with `protein_mpnn`.
4. Predict structures with `alphafold` (single-sequence path).
5. Filter by pLDDT and motif RMSD; reject scaffolds that distort the motif.

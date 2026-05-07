---
id: binder_design
version: 1
name: Binder Design
description: Design a small protein binder for a given target structure.
applicable_tasks: [binder_design]
provenance: human_authored
parent_version: null
---

> Phase 3 placeholder. Real workflow content authored in Phase 6.

## Inputs

- Target PDB id or structure file.
- Optional hotspot residues on the target.

## Steps

1. Retrieve target structure with `rcsb`.
2. Identify candidate hotspots if not provided.
3. Generate backbones with `rfdiffusion3`.
4. Design sequences with `protein_mpnn`.
5. Predict structures with `alphafold` (single-sequence path is fine for screening).
6. Rank by pLDDT, interface SASA, and clash score.
7. Filter by novelty using `foldseek`.

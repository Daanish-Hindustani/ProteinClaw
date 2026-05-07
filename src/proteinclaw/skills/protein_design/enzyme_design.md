---
id: enzyme_design
version: 1
name: Enzyme Design
description: Improve enzyme stability or activity by sequence redesign on a fixed scaffold.
applicable_tasks: [enzyme_design]
provenance: human_authored
parent_version: null
---

> Phase 3 placeholder. Real workflow content authored in Phase 6.

## Inputs

- Scaffold PDB.
- Catalytic residues to preserve.

## Steps

1. Retrieve scaffold with `rcsb`.
2. Identify mutable positions, preserving catalytic residues.
3. Design sequences with `protein_mpnn` (constrain catalytic positions).
4. Predict structures with `alphafold` and verify the catalytic geometry is preserved.
5. Rank by pLDDT and active-site RMSD relative to the scaffold.

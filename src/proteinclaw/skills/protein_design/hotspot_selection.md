---
id: hotspot_selection
version: 1
name: Hotspot Selection
description: Select target hotspot residues to drive binder or interface design.
applicable_tasks: [hotspot_selection, binder_design]
provenance: human_authored
parent_version: null
---

> Phase 3 placeholder. Real workflow content authored in Phase 6.

## Inputs

- Target PDB id or structure.
- Optional disallowed regions (membrane, signal peptides, etc.).

## Steps

1. Retrieve the target with `rcsb`.
2. Compute solvent accessibility per residue.
3. Identify clusters of exposed, conserved residues.
4. Rank candidate hotspots by exposure and conservation.
5. Return the top candidates as input for `binder_design`.

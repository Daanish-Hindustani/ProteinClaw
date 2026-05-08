---
id: binder_design
version: 2
name: Binder Design
description: De novo protein binder design against a target structure with hotspot guidance.
applicable_tasks: [binder_design]
provenance: human_authored
parent_version: 1
---

## Goal

Generate small (60-120 residue) de novo protein binders that engage a defined surface on the target with high pLDDT, low predicted clash, and demonstrable structural novelty.

## Inputs

- `target_pdb_id` — RCSB PDB id of the target.
- `hotspot_residues` — optional list (e.g. `["A45", "A46", "A52"]`). When omitted, identify with the `hotspot_selection` skill first.
- `binder_length_range` — default `60..120` residues.

## Steps

1. **Retrieve target.** Call `rcsb` with `pdb_id`. Read sequence + length from the response. If the target is a multimer, slice to the relevant chain before downstream tools.
2. **Construct contigs.** A contig string fixes the target chain and leaves the binder length free. For chain A residues 1-150 + a 60-100 binder: `A1-150/0 60-100`. The trailing `0` is the chain break; lengths after specify the free segment.
3. **Generate backbones.** Call `rfdiffusion3` with `target_pdb_path`, the contig string, and `hotspot_residues`. Sample at least 4 backbones (`num_designs=4` minimum; 8-16 for production runs). RFdiffusion guides docking via the hotspots.
4. **Design sequences.** For each backbone, call `protein_mpnn` with `backbone_pdb_path` and `num_sequences=8`. Lower `sampling_temperature` (0.1) for higher-confidence sequences; raise to 0.3 to broaden the candidate pool.
5. **Predict structure.** For each sequence, call `alphafold`. Single-sequence prediction (`msa=None`) is sufficient for *de novo* designs without natural homologs; supply an MSA only when refining toward known scaffolds.
6. **Score and rank.** Per candidate:
   - **pLDDT ≥ 0.80** is the working threshold for confident folds.
   - **pTM ≥ 0.70** indicates plausible global topology.
   - **Interface SASA** — buried surface area between binder and target chain; ≥ 600 Å² for a credible interface.
   - **Clash score** — < 5.0 (Phenix scale) on the binder + interface region.
7. **Filter for novelty.** Call `foldseek` against the PDB database. A top hit with TM-score < 0.5 indicates the binder is structurally distinct; ≥ 0.7 suggests recapitulating a known fold and may not be desirable for novel binder claims.
8. **Return ranked candidates.** Order by composite score; surface the top 3 with full metric breakdown.

## Common pitfalls

- **Hotspots too far apart.** RFdiffusion struggles when hotspots span > 25 Å or sit on opposite faces; the resulting binder often fails to dock cleanly. Pre-cluster hotspots before calling.
- **Excessive contig flexibility.** Long free segments (> 120 residues) waste compute and tend to produce low-pLDDT designs.
- **Trusting AF single-sequence predictions on natural-like sequences.** When ProteinMPNN converges on a sequence resembling a known fold, AF without MSA can be misleading; cross-check with Foldseek.

## Worked example

> Target: 1ABC chain A. Hotspots: A45, A46, A52. Binder length: 80.

```text
contigs = "A1-150/0 80-80"
rfdiffusion3 → 4 backbones
protein_mpnn (per backbone) → 8 sequences each
alphafold (per sequence) → 32 predictions
filter pLDDT >= 0.80, pTM >= 0.70 → typically 3-6 survivors
foldseek (per survivor) → keep TM-score(top hit) < 0.5
rank by interface_SASA descending
```

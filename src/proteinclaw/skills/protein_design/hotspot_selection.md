---
id: hotspot_selection
version: 2
name: Hotspot Selection
description: Select target hotspot residues that drive binder or interface design.
applicable_tasks: [hotspot_selection, binder_design]
provenance: human_authored
parent_version: 1
---

## Goal

Identify a small set (typically 3-5) of target residues that any successful binder must engage. Hotspots seed `binder_design` by telling RFdiffusion *where* on the surface to dock.

## Inputs

- `target_pdb_id` — PDB id of the target.
- `disallowed_regions` — optional segments to exclude (signal peptides, transmembrane spans, glycosylation sites).
- `desired_count` — number of hotspots to return (default 4; useful range 3-6).

## Steps

1. **Retrieve target.** Call `rcsb`. Confirm chain and read sequence length.
2. **Compute solvent accessibility per residue.** Use the Python sandbox (`sandbox`) with a small RSA / SASA script (e.g. via Biopython + DSSP, or the `freesasa` package). A residue is *exposed* when relative SASA ≥ 0.20.
3. **Identify candidate clusters.** Among exposed residues, find clusters whose Cα atoms are within 8-10 Å of each other in 3D. Singletons rarely make good hotspots; aim for residue trios or quartets that lie on a contiguous surface patch.
4. **Filter by conservation.** When a multiple sequence alignment or UniProt conservation track is available, prefer residues with conservation score ≥ 0.7 — they tend to be functionally relevant. Without conservation data, fall back on chemical-class heuristics (charged/polar residues are usually better hotspots than buried hydrophobics).
5. **Drop disallowed regions.** Remove anything in `disallowed_regions` (signal peptides, transmembrane, post-translational modification sites).
6. **Score and rank candidates.**
   - **Exposure score** — relative SASA averaged over the cluster.
   - **Cluster compactness** — inverse mean Cα-Cα distance (tighter clusters dock more cleanly).
   - **Functional priors** — bonus when hotspots overlap UniProt-annotated functional sites or ligand-binding pockets.
7. **Return the top `desired_count`.** Output as `["A45", "A46", "A52", "A78"]` shape — directly consumable by `binder_design`.

## Common pitfalls

- **Picking buried residues.** Easy to do when filtering by conservation alone; a buried conserved residue cannot be engaged from outside.
- **Hotspots > 25 Å apart.** RFdiffusion struggles to design a single binder that reaches all of them. Cluster compactness matters as much as exposure.
- **Ignoring symmetry.** On homo-multimers, equivalent residues across chains often appear as separate "hotspots"; consolidate to the relevant chain before passing downstream.
- **Mistaking flexible loops for hotspots.** Loop residues with high B-factors or low pLDDT in the target structure are unreliable docking points; prefer secondary-structure-anchored residues.

## Worked example

> Target: 1ABC chain A. Disallowed: signal peptide A1-22.

```text
sandbox: compute relative SASA per residue (DSSP)
filter rsa >= 0.20 and not in disallowed → ~30 exposed candidates
cluster by Cα distance ≤ 8 Å → ~6 clusters of size 3-5
rank by (exposure, compactness, conservation)
return top 4 cluster representatives → ["A45", "A46", "A52", "A78"]
```

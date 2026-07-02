---
name: proteinclaw-learned-target-resolution
description: "ProteinClaw learned guidance: target-resolution."
---

# Learned: target resolution (data.pdb_fetch)

Durable, cross-target lessons about resolving a target PDB/chain/crop before the GPU pipeline.
Keep this skill concise and procedural. Patch or rewrite stale guidance when a better rule is known;
do not preserve obsolete instructions as an append-only log. Use dated provenance only when it helps
explain why the rule exists.

## Target-resolution checklist

Use this checklist before RFdiffusion3, AF2-multimer, or nanobody screening:

1. Resolve the target identity to a specific entity: PDB chain, UniProt accession, user FASTA,
   or user-provided structure path.
2. Confirm chain letters and biological assembly. Crystal asymmetric units can include duplicate
   chains, ligands, antibodies, receptors, or scaffold partners that should not enter the target crop.
3. Inspect ordered protein residues separately from waters, ligands, glycans, and other HETATM records.
4. Choose the smallest biologically defensible crop that contains the intended epitope and required
   structural context. Avoid full-length membrane proteins in AF2-multimer unless the user explicitly
   wants that artifact-prone experiment.
5. Preserve original residue numbering in `plan.md`. When passing a crop into AF2, record `crop_start`
   so hotspot satisfaction can map original residue IDs to renumbered AF2 target chains.
6. If PDB evidence and UniProt sequence disagree, log the discrepancy and prefer the structure actually
   used by the downstream tool.

## Learned (run 45df3147af56, 2026-05-26): the reported chain residue count includes ordered waters/HETATM — crop to the protein range, not the chain length
On 1UBQ, `data.pdb_fetch` reported chain A as "134 residues, 1-134, contiguous, **no gaps**", and the
chain-inspection envelope likewise gave `residues_present_first_last: [1,134]`, `gaps: []`. But ubiquitin
is a 76-aa β-grasp domain — only residues 1-76 are protein (602 ATOM atoms; last ATOM = GLY A 76); residues
77-134 are 58 ordered crystallographic **waters** (HETATM) that the tool counts as chain residues. Cropping
naively to the reported `1-134` would feed 58 waters to RFD3 as "target residues."
**Fix / generalizes to any crystal structure with ordered solvent or ligands modeled in the protein chain:**
the gap inspector's clean `gaps: []` does NOT mean the whole range is protein. Before choosing a crop,
verify the true protein span — e.g. a one-line `Bash` check for the last `^ATOM` residue
(`grep '^ATOM' file.pdb | tail -1`) or compare ATOM vs HETATM counts — and crop to the folded domain
(here `A/1-76`), not to `residues_present_first_last`.

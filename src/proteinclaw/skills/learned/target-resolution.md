# Learned: target resolution (data.pdb_fetch)

Durable, cross-target lessons about resolving a target PDB/chain/crop before the GPU pipeline.
Append-only — add a new dated block, never rewrite an existing one. Correct a stale block by
appending a new block that starts `Correction:`.

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

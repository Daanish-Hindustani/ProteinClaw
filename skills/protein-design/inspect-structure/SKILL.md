---
name: inspect-structure
description: Use inspect_structure to inspect local PDB/CIF files for chain IDs, residue ranges, gaps, HETATM records, and resolution before RFD3 or ProteinMPNN.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, structure, pdb, cif, inspection]
    related_skills: [rcsb-search, rfd3-design, protein-binder-design]
---

# Inspect Structure

Use `inspect_structure` before building RFD3 contigs or selecting
ProteinMPNN-designed chains from a local structure file.

The tool is local and lightweight. It does not use Docker and should be
preferred over ad hoc shell parsing or installing structure-parsing packages.

## Workflow

1. Call `inspect_structure` with the downloaded or generated PDB/CIF path.
2. Check `chains` for residue counts, overall ranges, continuous ranges, and
   gaps.
3. Check `hetatm_records` and `hetatm_comp_ids` for ligands, chromophores,
   ions, waters, cofactors, and modified residues.
4. Use `resolution` when comparing experimental target structures.
5. Build contigs and hotspots only from residue IDs that exist in the inspected
   file.

## Design Notes

- Gaps often come from missing density, chromophores, modified residues, or
  intentionally omitted regions. Split RFD3 fixed target ranges at real gaps.
- For GFP-like targets, chromophores may appear as HETATM records and interrupt
  the polymer residue numbering.
- RFD3 outputs may remap chain IDs. Inspect generated structures before running
  ProteinMPNN so `designed_chains` targets the binder, not the target.

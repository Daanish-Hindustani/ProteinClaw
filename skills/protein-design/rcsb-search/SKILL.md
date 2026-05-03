---
name: rcsb-search
description: Use rcsb_search to find experimental protein structures, inspect metadata, identify chains/ligands, and download target structures for design.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, rcsb, pdb, structure]
    related_skills: [uniprot-search, inspect-structure, rfd3-design]
---

# RCSB Search

Use `rcsb_search` when the task needs an experimental structure, PDB metadata,
chain IDs, ligand context, structure download, or a target file for RFD3/MPNN.

## Workflow

1. Search by text, sequence, UniProt accession, or ligand.
   - If the user provides known PDB IDs, call `rcsb_search` with `pdb_ids`
     instead of text search.
2. Prefer high-resolution structures with relevant biological assemblies and
   bound ligands/cofactors when those matter for the design goal.
3. Check experimental method and resolution before trusting a structure.
4. Download structures when they will feed RFD3, ProteinMPNN, or local parsing.
   - Use `download_format="pdb"` when a downstream step needs strict PDB
     columns.
   - Use `download_format="cif"` when preserving mmCIF metadata matters.
5. Use the returned `chains` metadata to check chain IDs, residue ranges,
   continuous ranges, and gaps. Confirm against the actual downloaded file when
   the design depends on exact residue numbering.
6. Use `inspect_structure` for local/generated structures or when you need
   HETATM records and resolution alongside chain ranges.

## Design Notes

- For RFD3 contigs, chain IDs and residue numbers must match the file.
- Avoid dragging unnecessary chains into design inputs; include the minimal
  target/interface context that preserves the biology.
- For ligand-aware design, keep the ligand-containing structure and record the
  ligand three-letter code.
- Downloaded asymmetric units may contain multiple copies of the same protein.
  Pick the intended monomer/chain before building contigs or hotspots.

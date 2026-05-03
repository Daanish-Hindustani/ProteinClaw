---
name: uniprot-search
description: Use uniprot_search to discover protein targets, reviewed sequences, functional annotations, domains, features, and PDB cross-references.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, uniprot, sequence, target-discovery]
    related_skills: [rcsb-search, esmfold-predict]
---

# UniProt Search

Use `uniprot_search` when the task needs a canonical protein sequence, gene to
protein mapping, functional annotation, domain boundaries, organism scoping, or
PDB cross-references.

## Workflow

1. Prefer reviewed Swiss-Prot entries for canonical target selection.
2. Scope by `organism_id` whenever the organism matters.
3. Use `gene` when a gene symbol is known; use free text when only the protein
   name or family is known.
4. Pull sequence, length, function comments, domains/features, and PDB refs.
5. Use PDB refs as seeds for `rcsb_search` before RFD3 target design.

## Interpretation

- Domain and feature annotations are useful for deciding what region to design
  against or fold.
- Isoforms and fragments can differ materially; do not assume the first hit is
  the correct biological construct.
- If no reviewed hit exists, say so and treat TrEMBL records as lower confidence.

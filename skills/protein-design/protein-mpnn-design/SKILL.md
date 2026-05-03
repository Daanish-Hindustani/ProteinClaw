---
name: protein-mpnn-design
description: Use protein_mpnn_design for fixed-backbone sequence design after RFD3 or with existing structures.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, proteinmpnn, ligandmpnn, sequence-design]
    related_skills: [rfd3-design, esmfold-predict]
---

# ProteinMPNN Design

Use `protein_mpnn_design` to design amino-acid sequences for fixed protein
backbones. It is typically run after RFD3 generates candidate backbones.

`protein_mpnn_design` assumes the Foundry Docker image is already installed. Do
not pull or build Docker images from this skill. If local compute is missing,
report the setup requirement and continue planning.

## Workflow

1. Start from a valid PDB/CIF backbone.
2. Choose `model_type`:
   - `protein_mpnn` for protein-only fixed-backbone design.
   - `ligand_mpnn` when ligand, ion, DNA/RNA, or other atom context matters.
3. Set `designed_chains` when only some chains should change.
4. Set `fixed_positions` when catalytic/interface residues must remain fixed.
5. Pass a directory or `structure_paths` list when designing sequences for a
   batch of RFD3 backbones.
6. Generate multiple sequences and keep diversity.
7. Validate outputs with `esmfold_predict`.
8. Feed failures back into the binder campaign: adjust temperature, fixed
   positions, or backbone selection before generating another sequence batch.

## Temperature Guidance

- `0.05-0.1`: conservative, higher confidence, less diverse.
- `0.2-0.3`: more diverse, useful after initial candidates pass validation.
- Avoid presenting high-scoring sequences as experimentally validated.

## Binder Iteration

For binder campaigns:

- Start with `temperature=0.1` on several RFD3 backbones.
- If ESMFold confidence is good but sequences are too similar, run a second
  batch at `0.2-0.3`.
- If folds collapse or confidence drops, lower temperature or return to RFD3 for
  new backbones.
- Keep the sequence design settings with each candidate so the agent can rank
  and reproduce the current best binder candidate.

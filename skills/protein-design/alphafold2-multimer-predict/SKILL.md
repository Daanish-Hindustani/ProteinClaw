---
name: alphafold2-multimer-predict
description: Use alphafold2_multimer_predict to predict binder-target complex structures with an AlphaFold2/ColabFold multimer container.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, alphafold2, colabfold, multimer, complex, validation]
    related_skills: [inspect-structure, rfd3-design, protein-mpnn-design, esmfold-predict]
---

# AlphaFold2 Multimer Predict

Use `alphafold2_multimer_predict` when a binder candidate should be evaluated
as a complex with its target. This is stronger validation than folding the
binder alone with ESMFold, but it is still computational triage rather than
measured affinity.

The tool expects a compatible AlphaFold2/ColabFold Docker image. The default
command shape is `colabfold_batch`; if your image uses a different command,
pass `command` or configure `protein_design.alphafold2_command`.

## Workflow

1. Choose a small set of promising candidates after RFD3, ProteinMPNN, and
   ESMFold triage.
2. Provide either:
   - `binder_sequence` and `target_sequence`
   - a colon-separated `sequence`, e.g. `BINDER:TARGET`
   - `sequences` as an ordered chain list
   - `fasta_path`
3. Start with a modest `num_recycles` for screening.
4. Inspect predicted complex confidence and interface geometry before ranking.

## Interpretation

- AF2/Multimer can suggest whether the binder and target form a plausible
  complex, but it does not directly measure affinity.
- High confidence away from the interface is not enough; inspect interface
  confidence and contacts.
- Watch for target-dominated predictions where the binder is low-confidence,
  detached, or collapsed onto the wrong surface.
- Keep AF2 complex results alongside RFD3 settings, ProteinMPNN temperature,
  ESMFold confidence, and any experimental assumptions.

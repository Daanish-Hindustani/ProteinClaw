---
name: esmfold-predict
description: Use esmfold_predict to fold designed or natural sequences locally with ESMFold and interpret pLDDT confidence.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, esmfold, folding, validation]
    related_skills: [protein-mpnn-design, uniprot-search]
---

# ESMFold Predict

Use `esmfold_predict` to locally fold amino-acid sequences and triage designed
proteins before deeper validation.

`esmfold_predict` assumes the ESMFold Docker image is already installed. Do not
pull or build Docker images from this skill. If local compute is missing, report
the setup requirement and continue planning.

## Workflow

1. Fold designed sequences after ProteinMPNN, or a natural/user-provided
   sequence when explicitly useful.
   - Do not call this tool without `sequence` or `fasta_path`.
2. Use `num_recycles=4` by default; increase when the structure is large or
   borderline and runtime is acceptable.
3. Use `chunk_size` or `cpu_offload` for memory pressure.
4. Inspect mean pLDDT and local low-confidence regions.
5. Reject or redesign candidates with poor global confidence, broken topology,
   or low-confidence interface/motif regions.
6. For binder campaigns, fold enough sequence variants to compare candidates
   across RFD3 and ProteinMPNN parameter settings.

## Interpretation

- The tool summary reports pLDDT on a `0-100` scale.
- In ESMFold output PDB files, pLDDT may appear in the B-factor column on a
  `0-1` scale depending on the implementation path. When parsing B-factors
  directly, inspect the value range and multiply by `100` before applying the
  thresholds below if values look like `0.58` instead of `58`.
- Mean pLDDT `>80`: high confidence; usually worth finalist consideration.
- Mean pLDDT `65-80`: moderate confidence; keep as candidates if topology and
  design context look plausible.
- Mean pLDDT `50-65`: borderline; usually needs redesign or parameter tuning.
- Mean pLDDT `<50`: likely disordered, misfolded, or not worth pursuing without
  a specific reason.
- High pLDDT does not prove binding, catalysis, expression, or stability.
- Low confidence at flexible termini may be acceptable; low confidence in the
  designed core, active site, or binding interface is a serious warning.

## Binder Ranking Use

Use ESMFold as a triage signal, not the final binder score:

- Use `num_recycles=4` for broad screening.
- Re-run finalists with higher `num_recycles` when runtime allows.
- Prefer candidates with confident binder cores and stable topology across close
  sequence variants.
- If the binder folds well but binding is uncertain, preserve it as a finalist
  and recommend downstream interface scoring or experimental validation.

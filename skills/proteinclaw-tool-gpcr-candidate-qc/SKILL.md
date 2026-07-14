---
name: proteinclaw-tool-gpcr-candidate-qc
description: Apply fail-closed, manifest-aware geometric QC to predicted GPCR nanobody complexes.
---

# GPCR nanobody candidate QC

Run `analysis.gpcr_candidate_qc` on every final BoltzGen complex before spending
GPU time on orthogonal AF-M confirmation. Pass the exact schema-v2 target
manifest used for generation. For BoltzGen outputs the receptor is normally
chain A and the VHH chain B; verify rather than assume when another engine
produced the complex.
For state-conditioned Boltz-2 outputs, pass
`target_numbering="prediction_sequence"`. Boltz-2 numbers the resolved target
sequence from one, so the tool must derive an author-to-prediction map from the
prepared GPCR before evaluating intended or forbidden residues. Never compare a
Boltz-2 complex directly to manifest label numbers.
Pass the matching BoltzGen intermediate `.npz` as `design_mask_path`; the tool
derives the exact scaffold-specific CDR1/2/3 ranges. For imported candidates,
pass explicit `cdr_ranges` JSON instead. Missing CDR provenance fails closed.

The structural-triage gate requires at least 90% of intended hotspots to map,
mapped intended-hotspot satisfaction, calibrated interface BSA, reference-like
clashes, confident interface/CDR3 geometry, and zero contacts to
`excluded_residues_label`. A missing or unverified mapping or confidence value
fails closed. Pass `reference_complex_path` for a solved complex on the same
receptor face and state when possible; the tool narrows BSA to 0.65–1.35 times
the reference and the clash ceiling to the tighter of 5.0 or reference + 3.0.
Do not reuse generic soluble-protein cutoffs for recessed GPCR interfaces.

Reject any candidate with a forbidden-face contact, less than 50% intended
hotspot satisfaction, less than 60% of binder interface residues in CDRs,
interface/CDR3 confidence below 0.70, or excessive clashes. The normalized
confidence fields accept either native 0–1 values or pLDDT-style 0–100 values.
`passes_strict_gate` and `eligible_for_afm_confirmation` describe this
structural-triage decision only.

For state-dependent GPCR binders, prefer five state-conditioned Boltz-2 samples
for the candidate, matched control, and receptor counterstate. Require every
intended-state sample to beat every counterstate sample on ipTM and interface
confidence, plus intended-face QC on every promoted intended-state prediction.
Use the legacy AF-M confirmation gate below only when positive-control
calibration shows that sequence-only prediction retains the relevant interface.

The legacy `analysis.gpcr_confirmation_gate` fails closed unless:

- five complete candidate and control models were scored;
- candidate mean ipTM is at least 0.60, interface pLDDT at least 87, interface
  PAE at most 10, and model contact support at least 2.5;
- at least half of contacts recur in three of five models, mean pairwise
  contact Jaccard is at least 0.30, and ipTM standard deviation is at most 0.10;
- the candidate beats the matched control by at least 0.10 ipTM, 0.03 composite
  score, and 2.0 Å interface PAE when the control has a modeled interface.

Hotspot coverage or BSA can never compensate for a failed confidence,
physicality, reproducibility, or control-separation check. Treat a confirmation
pass as an experimental priority, not evidence of binding. Record Worked / Why /
Gap / Next in `plan.md`.

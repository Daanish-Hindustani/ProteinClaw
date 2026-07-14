---
name: proteinclaw-tool-boltz2-gpcr
description: Use state-conditioned Boltz-2 to confirm GPCR nanobody candidates against verified receptor templates, epitope constraints, positive controls, and matched negative controls.
---

# State-conditioned Boltz-2 GPCR confirmation

Use `proteinclaw_structure_boltz2_gpcr` only after
`proteinclaw_data_gpcr_target_prepare` produced a schema-v3 manifest with
verified numbering, topology, state markers, and
`confirmation_state_preserved=true`.

This tool fixes the receptor to the experimentally observed target template
within a disclosed tolerance, conditions on the adjudicated epitope, and lets
Boltz-2 predict the nanobody pose. It does not template the binder pose.

## Calibration before candidates

1. Run an exact experimentally validated nanobody for the same receptor face
   and state. For μOR, use Nb39/Nb63 for the active intracellular face or NbE
   for the extracellular face.
2. Run a matched nonbinder or CDR-scrambled control with the exact same target
   manifest, MSA mode, template threshold, pocket settings, potentials,
   recycling steps, and sample count.
3. If the known positive does not separate from the control, mark the tool
   uncalibrated for that target representation. Do not use its absolute scores
   to eliminate novel candidates.

## Candidate confirmation

- Use one sample only for an explicit diagnostic or pipeline smoke test.
- Use five diffusion samples for promotion evidence.
- Keep `force_template=true`; changing it destroys state conditioning.
- Keep `force_pocket=false` for the primary comparison. A forced-pocket run is
  a sensitivity analysis and must never be mixed with unforced controls.
- Keep physical potentials enabled and disclose the template threshold.
- Require intended-face recovery with deterministic
  `proteinclaw_analysis_gpcr_candidate_qc` on every promoted predicted complex,
  with `target_numbering="prediction_sequence"`.
- Compare candidate and matched control distributions, not only the best
  sample. Require reproducible interface geometry and a clear confidence/ipTM
  margin over the control.
- For a state-selective hypothesis, prepare a matched counterstate manifest
  with the same biological face and homologous author-numbered anchors. Require
  the entire intended-state distribution to exceed the counterstate
  distribution before promotion.

Boltz-2 scores are computational prioritization. They are not experimental
binding, affinity, state selectivity, or developability measurements.

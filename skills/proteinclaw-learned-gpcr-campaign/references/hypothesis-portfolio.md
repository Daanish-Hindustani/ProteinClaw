# GPCR hypothesis portfolio contract

Use this reference when planning or adjudicating a GPCR nanobody campaign.

## Research dossier

Do not generate designs until the run records a compact dossier with:

- receptor identity, species, isoform, construct mutations and missing residues;
- at least one structure for every state being tested, including ligand,
  transducer/nanobody, resolution, and author-to-label numbering provenance;
- seven transmembrane spans, membrane normal, extracellular/intracellular loop
  exposure, glycosylation sites, disulfides, unresolved loops, and retained
  cofactors;
- residue-level contacts from experimentally solved complexes on the relevant
  receptor or a justified homolog;
- intended biological mechanism: extracellular antagonist/agonist, allosteric
  modulator, or intracellular state sensor;
- known positive complexes and mismatched/non-binding controls used to calibrate
  every promotion metric.

Claims that determine an epitope or state require a primary structural source
and coordinate verification. A review may orient the search but cannot be the
only evidence for a design decision.

## Hypothesis card

Represent every hypothesis as a falsifiable card in `plan.md` or a JSON run
artifact:

```text
id; mechanism; receptor structure/state; binding side; positive anchors;
forbidden residues; approach direction; scaffold family; expected contact
pattern; positive reference; negative controls; uncertainties; cheap test;
promotion rule; pivot if falsified
```

The portfolio must contain structurally distinct cards, not superficial changes
to residue lists. For a GPCR, useful axes include active versus inactive state,
extracellular pocket versus loop/vestibule versus intracellular effector face,
and generic versus experimentally derived VHH scaffold.

## Explore then exploit

Explore 3–6 hypotheses concurrently (2–8 only when justified) with the minimum valid generation batch
(normally four designs each). Apply mapping/topology QC, liability filtering,
pose clustering, and one-model AF-M triage. Compare each branch with its matched
positive reference and at least one negative control.

Promote at most one or two hypotheses. A hypothesis earns an 8–16-design depth
round only when at least one candidate:

- has complete metrics and correct state/face geometry;
- passes reference-calibrated clash/BSA/CDR checks;
- has stronger independent interface evidence than its matched negative;
- contributes a pose or sequence cluster not already represented.

If no branch separates from controls, hold a synthesis debate and change the
target representation, state, epitope geometry, scaffold prior, or confirmation
model. Increasing candidate count is not a valid pivot.

## Final promotion

Require five-model or multi-seed confirmation, consistent epitope/pose support,
negative-control separation, counter-state/counter-target specificity where
relevant, and developability checks. Preserve the metric vector and uncertainty;
never collapse evidence into an unsupported universal binder score.

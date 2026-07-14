---
name: proteinclaw-learned-gpcr-campaign
description: Persistent, active-learning campaign policy for small-set GPCR nanobody discovery.
---

# Learned GPCR campaign policy

Use alongside `proteinclaw-workflow` and `proteinclaw-nanobody` for a long-lived
campaign (for example, a mu-opioid receptor VHH program). The objective is a
small, experimentally useful shortlist, not a large virtual library.

## State machine

Persist a campaign state in `plan.md`: `hypothesis -> research -> prepare ->
design -> deterministic_qc -> orthogonal_confirm -> adjudicate -> pivot`.
Every transition records inputs, outputs, and a Worked / Why / Gap / Next
retrospective. Resume this state after interruption; never restart from an
empty hypothesis. Three rounds are a review checkpoint only.

## Research and hypothesis portfolio

Before generation, read
[`references/hypothesis-portfolio.md`](references/hypothesis-portfolio.md) and
write its research dossier plus falsifiable hypothesis cards into run artifacts.
Verify epitope-defining claims in primary structural sources and the actual
coordinates. Debate the full portfolio, including target representation and
controls, rather than debating only which candidate to rank.

## Active-learning rounds

Start with 3–6 structurally distinct hypotheses (state, receptor face, epitope,
approach vector, construct, or scaffold prior) encoded in a persisted
`data.gpcr_hypothesis_portfolio`, and include matched positive and negative
controls. Every card carries structured experimental evidence, counterstate
and reference structures, an observed scaffold prior, a falsifiable prediction,
and its dominant risk. Explore with the minimum valid batch, normally four
conditional designs per hypothesis. Only a branch that separates from controls
earns an 8–16-design depth round, and at most two branches may be promoted.
Retain ≤4–8 diverse candidates for GPU confirmation and ≤12 for the campaign
shortlist. Select the next round by information gained: change one variable
(epitope geometry, state, target representation, scaffold/CDR regime, or model)
based on the dominant failure mode. Do not increase sample count to compensate
for an untested or contradicted hypothesis.

## Evidence and controls

Rank with a metric vector, not one score: mapped-hotspot fraction, forbidden
face contacts, CDR contact fraction, ipTM/ipSAE, interface confidence, BSA,
clashes, membrane penetration, and reproducibility across five AF-M models.
Run matched positive references and negative controls (wrong face,
scrambled/decoy VHH, counter-state, or unrelated surface). Calibrate geometry
and confidence against solved complexes. Missing metrics or failed residue
mapping are rejection reasons, not zeros. Geometry-only QC can eliminate a
candidate but cannot promote one; promotion requires independent model support
and control separation.
Use `analysis.gpcr_candidate_qc` for structural triage and
`analysis.gpcr_confirmation_gate` for final computational promotion. The final
gate requires a complete five-model candidate/control pair, stable contact
geometry, and explicit candidate-control score separation. Hotspot satisfaction
and BSA alone are never sufficient.
Sequence-only AF-M loses the selected receptor conformation and therefore
cannot confirm active/inactive state selectivity. Preserve state in at least
one confirmation path or keep the state-selectivity claim unresolved.

## Pivot and stopping policy

After two weak rounds, hold a synthesis/debate round that compares all failure
clusters and selects a genuinely different hypothesis or confirmation model.
Stop only when the strict nanobody gate has orthogonal support and a compact
shortlist, the user stops the campaign, or a documented scientific/resource
blocker prevents progress. A zero-hit round is a result to learn from; record
it and pivot. Never claim experimental affinity from computational scores.

## Reproducibility

Keep immutable target manifests, source PDB/mmCIF identifiers, random seeds,
tool/model versions, and negative-control definitions in run artifacts. Record
all OOMs, stubs, skipped stages, and bounded retries. Promote a lesson to this
skill only when it changes a future decision rule.

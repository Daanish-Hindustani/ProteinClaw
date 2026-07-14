---
name: proteinclaw-nanobody
description: State-aware, small-set ProteinClaw workflow for designing and evaluating VHH/nanobody binders to GPCRs.
---

# Nanobody-vs-GPCR design skill (small, hypothesis-driven set)

This is a VHH design workflow, not a blind library screen. Codex must run the
base ProteinClaw workflow first: create/resume a run, research with native web
tools, record evidence, perform due diligence, debate the epitope and state,
then execute tools. Record every round in `plan.md` with Worked / Why / Gap /
Next. ProteinClaw outputs are computational candidates, never validated binders.

Campaigns are persistent. A research-backed baseline, adversarial refinement,
and independent confirmation are the first checkpoint, not a three-round stop
condition. Keep the same `run_id`, append decisions to `plan.md`, resume after
interruption, and continue bounded hypothesis rounds until the strict gate has
orthogonal support or a documented blocker/user stop ends the campaign.

## Cardinal rules

1. Use a researched, intact GPCR chain and explicitly record extracellular vs
   intracellular side, receptor state, epitope residues, exclusions, and source.
   Do not silently crop away the receptor or let a model choose the face.
2. Use `data.gpcr_target_prepare` to validate and stage the full target chain,
   then `design.boltzgen_nanobody` for a small first round (8–16 designs;
   configurable 4–64, with a final diversity budget ≤12). The tool is a
   hypothesis test, not a 10,000-member production campaign.
3. Read the scoped tool skill before each tool. Use `--reuse` for interrupted
   BoltzGen rounds and keep all stages in the same session workspace.
4. Use AF2/AF-M and interface metrics as orthogonal confirmation on only the
   top few candidates. A single confidence score is never proof of binding.
5. Retry a failed tool at most once, record the failure, and continue or stop.
6. Require original mmCIF author-to-label mapping, membrane-core spans, at
   least two positive anchors, and at least two opposite-face exclusions.
   Generation fails closed when any of these are missing.
7. Never remove `binding` or `not_binding` conditioning after a parser error.
   Correct the numbering/specification and run `boltzgen check` again.

## Round protocol

1. Research target identity, isoform, PDB/UniProt mapping, ligand and state,
   known nanobody interfaces, missing loops, glycosylation and membrane risks.
2. Debate at least two epitope/state hypotheses. For μOR, distinguish an
   extracellular orthosteric/ECL hypothesis from an intracellular active-state
   effector-face hypothesis; use structures such as 8QOT and 5C1M as evidence.
   Encode 2–8 distinct proposals with `data.gpcr_hypothesis_portfolio`, including
   structured experimental evidence, counterstate/reference complexes,
   experimentally observed scaffolds, falsifiable predictions, and paired
   controls. Explore each with 2–6 designs before allocating an 8–16-design
   deep dive to at most two supported hypotheses.
3. Run `data.gpcr_target_prepare` with the source mmCIF and optional legacy PDB, adjudicated
   chain, author-numbered membrane spans, positive anchors, and wrong-face
   exclusions. Link the persisted portfolio and record construct/ligand
   context, unresolved/modelled regions, glycans, state markers, evidence, and
   reference/counterstate structures. Verify the manifest's label-numbered
   fields and `mapping_verified=true` before generation.
   For mmCIF-only RCSB entries, omit `target_pdb`; the tool derives a
   single-author-chain compatibility PDB and keeps the mmCIF as the canonical
   numbering source.
4. Run BoltzGen with `num_designs=8..16` and `budget=4..8`. Inspect native
   metric tables and retain only a small, diverse set for confirmation.
5. Run `analysis.gpcr_candidate_qc` on every finalist before expensive
   confirmation. Calibrate the confirmation model on an exact known positive
   and matched control for the same target representation. Prefer
   state-conditioned Boltz-2 for state-dependent GPCR interfaces; use
   AlphaFold2-multimer as a sequence-only diagnostic unless its positive-control
   recovery succeeds. Check reproducibility, mapped contacts, forbidden-face
   avoidance, clashes, calibrated buried area, CDR-driven contacts, and
   state/side consistency.
   Sequence-only AF-M does not retain an active/inactive input conformation;
   it cannot establish state selectivity without a state-preserving confirmation
   route or a genuinely state-specific construct.
6. Before each refinement round, research and debate again. Change one hypothesis
   variable (epitope, state, scaffold regime, or budget), document why, and
   run another bounded round. Zero finalists is valid, but does not end a
   campaign. After repeated failures, add a synthesis round and change the
   structural hypothesis or model rather than merely increasing sample count.

## Quality gate and reporting

There is no universal numeric “binder” threshold for a novel GPCR. Require a
complete metric record, physically plausible interface (no severe clashes or
membrane-penetrating pose), at least 50% mapped-hotspot satisfaction, zero
forbidden-face contacts, CDR-driven contacts, agreement across confirmation
models, and ranking above negative/control structures from the same run. Treat
AF-M `combo_feature`, ipTM, pLDDT, PAE, BSA, clash score, and predicted KD as
comparative evidence; predicted KD is advisory only. Calibrate BSA against a
known complex for the same receptor/face when available; μOR reference
interfaces are larger than generic soluble-protein heuristics. Missing metrics
fail confirmation. Report target resolution, state, assumptions, failed/skipped
tools, OOMs, and whether the strict quality gate was met.

## Legacy path

`design.nanobody_library` remains available for evaluation or controlled
baselines, but random/library-first generation is not the default GPCR path.
Do not call RFdiffusion3 or ProteinMPNN in this VHH workflow.

---
name: proteinclaw-tool-boltzgen-nanobody
description: Run a bounded BoltzGen nanobody design round against a prepared GPCR target.
---

# BoltzGen small-set nanobody design

This container tool is the generation step for the state-aware GPCR workflow.
It expects a manifest from `data.gpcr_target_prepare`, runs the
antibody-aware `nanobody-anything` protocol, and writes native BoltzGen metrics
and ranked structures. Explore with four intermediate designs per hypothesis;
increase to 8–16 and a final budget of 4–8 only after the branch separates from
its controls. `reuse=true` allows an interrupted round to resume without losing
progress.

## Design modes

`design_mode="de_novo"` is the backward-compatible default. It samples the
bundled generic VHH scaffold panel and is appropriate only when the hypothesis
really calls for a new scaffold/pose family.

Use `design_mode="scaffold_redesign"` for an experimentally grounded family
such as Nb39/Nb62 or NbE. Supply `scaffold_spec_path`,
`scaffold_structure_path`, and `scaffold_reference_id`. Both files must be in
the current session workspace. The reference ID must already appear in the
schema-v3 target manifest's `target_representation.reference_scaffold_ids`.
The scaffold YAML must include exactly one VHH chain, nonempty `design` ranges,
and both visibility-2 framework context and visibility-0 mutable regions. Only
positions in its `design` ranges can change, so preserve a validated CDR motif
or framework contact by leaving it outside those ranges. The YAML `path`
basename must match the supplied PDB/mmCIF file. The wrapper stages immutable
copies and records SHA-256 hashes in the result manifest.

Both modes deliberately keep the `nanobody-anything` protocol. BoltzGen's
generic `protein-redesign` protocol is not substituted silently because it
does not carry the same antibody-specific filtering and loop behavior. Treat
changing the scaffold or mutable ranges as a new hypothesis and record it in
the campaign plan.

The wrapper must fail closed unless the manifest is schema v2+, preserves the
full receptor, verifies topology and author-to-label mapping, and supplies at
least two mapped positive and negative residues. It consumes the prepared
mmCIF and label chain, never the author-numbered PDB fields. The generated
`binding_types` entry must contain both `binding` and `not_binding`; run
`boltzgen check` and treat any rejection as a numbering/spec bug. Never remove
a mask to get past the check. Scaffold redesign additionally requires schema
v3, workspace-contained inputs, experimental provenance declared in the
manifest, one included chain, explicit mutable residues, valid structure-group
visibility, and recognizable coordinate atom records. Missing or inconsistent
inputs are rejection reasons; do not fall back to the generic scaffold panel.

BoltzGen rankings are hypotheses. Inspect the metric tables and confirm only a
small diverse subset with independent AF2/AF-M/interface tools. Record output
paths, failures, GPU/OOM status, and the next hypothesis in `plan.md`.

Run `analysis.gpcr_candidate_qc` on every returned final structure before AF-M.
Reject wrong-face contacts and weak intended-hotspot satisfaction. Calibrate
interface area using a solved target-face complex when possible, then confirm
only the small strict-QC subset against same-run negative controls.

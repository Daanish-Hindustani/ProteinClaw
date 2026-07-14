---
name: proteinclaw-tool-gpcr-target
description: Prepare and validate an intact, state-annotated GPCR target for binder design.
---

# GPCR target preparation

Use this tool only after research, portfolio construction, and debate have
selected the PDB/chain, face, state, epitope residues, and exclusions. It
validates residue numbering and stages the complete selected chain; it does
not infer an epitope or receptor state. Pass the
`hypothesis_portfolio_path` when available so preparation fails if the selected
state, side, anchors, or exclusions drift from the adjudicated hypothesis.
Keep the output in the same session workspace as downstream design.

Always pass the original mmCIF. A legacy PDB is optional: for mmCIF-only RCSB
entries, omit `target_pdb` and the tool will create a single-chain PDB
compatibility view while preserving the requested author chain and author
residue numbers. The original mmCIF remains authoritative and is persisted.
PDB author residue numbers are not BoltzGen residue indices: the tool must
derive and persist the unique `auth_seq_id -> label_seq_id` mapping. Also pass author-numbered seven-TM
membrane-core spans, 2–12 positive surface anchors, and 2–32 wrong-face or
off-target exclusions. Positive anchors inside the membrane core are rejected.

The schema-v3 manifest is the design contract. In addition to coordinates,
record the stable receptor and hypothesis IDs, experimental method/resolution,
construct mutations/truncations/fusions, ligand and stabilizing-partner
context, unresolved and modelled regions, glycosylation sites, membrane-span
source, and at least one resolved activation-state marker. Binding anchors on
unresolved or modelled residues are rejected.

Every manifest must carry structured `experimental_evidence` with a DOI, PMID,
PDB ID, or stable URL, evidence type, directness, and residue-level claim.
Explicitly list experimental reference complexes, relevant observed VHH
scaffolds, and active/inactive counterstate structures; use empty lists only
when research proves none are available and treat the resulting warnings as a
campaign risk.

Require
`full_chain_preserved=true`, `mapping_verified=true`,
`topology_verified=true`, a nonempty `target_label_chain`, and mapped
`binding_residues_label` plus `excluded_residues_label`. Inspect the mapping
for representative residues before the GPU call. Do not hand-edit mapped
fields or fall back to the PDB after a mapping failure.

Inspect `target_representation.warnings` before design. In particular,
`sequence_only_state_uncontrolled` means AF2/AF-M receives only the receptor
sequence and therefore cannot confirm that the chosen active/inactive
conformation was preserved. Such a result may rank generic complex
plausibility but cannot establish state selectivity. Require a
structure-conditioned or state-specific-construct confirmation path before
promoting a state-selective binder claim.

A missing loop, ambiguous chain mapping, uncertain state, or disputed topology
is a reason to research, revise, or stop before generation. Record the source,
state/epitope rationale, and membrane-span provenance in the run plan.

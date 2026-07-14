---
name: proteinclaw-tool-gpcr-pose-refine
description: Transfer a solved homologous GPCR-VHH pose onto a verified receptor state, graft a small evidence-backed mutation set, and perform restrained OpenMM interface relaxation.
---

# GPCR solved-pose refinement

Use `proteinclaw_structure_gpcr_pose_refine` when an experimental homologous
GPCR-VHH binding pose exists and the campaign is optimizing that VHH family.
Do not ask a de novo predictor to rediscover a solved unusual pose.

Require a schema-v3 target manifest with verified author/label mapping,
topology, state markers, and an intact receptor chain. Pass the exact reference
complex and its receptor/VHH chains. Restrict `binder_mutations` to a small set
supported by binding, mutagenesis, or structural evidence, and pass the exact
expected final VHH sequence. A sequence mismatch fails closed.

The tool aligns shared transmembrane C-alpha atoms by author residue number,
transfers the reference VHH into the target frame, adds the declared side-chain
mutations, and minimizes in implicit solvent with receptor and VHH backbone
restraints. Record the alignment RMSD, atom count, restraint, OpenMM version,
platform, and energies. Reject an implausible alignment or construct mismatch.

Run `proteinclaw_analysis_gpcr_candidate_qc` on the refined complex with
`target_numbering="manifest_author"`. Keep the solved same-face complex as the
BSA/clash reference. Do not weaken hotspot, forbidden-face, CDR-driven,
confidence, or clash gates to make a transferred model pass.

Only after strict pose QC passes, use state-conditioned Boltz-2 as an
orthogonal candidate/control/counterstate comparison. The transferred complex
is a modeled experimental priority, not proof of binding, affinity, or state
selectivity.

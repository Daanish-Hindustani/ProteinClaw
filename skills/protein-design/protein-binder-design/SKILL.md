---
name: protein-binder-design
description: "Use for iterative protein binder design campaigns: define the target and epitope, generate binder backbones with RFD3, design sequences with ProteinMPNN, fold/triage with ESMFold, rank candidates, and tune parameters across rounds."
version: 1.1.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, binder-design, rfd3, proteinmpnn, esmfold]
    related_skills: [pubmed-search, uniprot-search, rcsb-search, inspect-structure, rfd3-design, protein-mpnn-design, esmfold-predict, alphafold2-multimer-predict]
---

# Protein Binder Design

Use this skill when the user wants to design, optimize, or rank a protein
binder against a target protein, domain, epitope, receptor, antigen, enzyme, or
protein complex.

This is a workflow skill, not a tool wrapper. The tools are independent. Choose
only the steps needed for the task; do not run the whole pipeline blindly. The
default posture is iterative: generate a small batch, score it, change one or
two parameters based on failure mode, and repeat until the best computational
candidate stops improving or the user's compute budget is reached.

## Compute Guardrails

Do not install, pull, or build local model images during a binder-design turn
unless the user explicitly asks for setup/installation. In particular, do not
use terminal commands such as `docker pull`, `docker build`, or `sudo docker`
just because RFD3, ProteinMPNN, or ESMFold are needed.

If local compute is not ready, report that and tell the user to run
`hermes setup tools` and choose `Protein Design` -> `Local Docker compute`, or
run `scripts/setup_protein_design_local.sh`. Then continue with literature,
target, structure, contig, hotspot, and parameter planning.

Only run heavyweight compute tools when all are true:

- The target/sequence/structure inputs are known and validated.
- The user asked to actually run designs or validation, not just plan.
- Local Docker images are expected to already exist.
- The run is a small debug job first, unless the user gave a larger budget.

## Campaign Workflow

1. Clarify the design objective.
   - Target protein and organism
   - Desired binding region, epitope, ligand pocket, or interface
   - Constraints: binder length, oligomeric state, disulfides, forbidden motifs,
     expression host, and whether wet-lab validation is planned
   - Compute budget: number of RFD3 rounds, designs per round, and acceptable
     runtime

2. Gather evidence with `pubmed_search` when biology or precedent is unclear.
   - Look for known binders, complexes, epitopes, mutational scans, domain
     boundaries, and interface structures.
   - Prefer papers with direct structural or biochemical evidence.

3. Resolve the target with `uniprot_search`.
   - Get canonical sequence, domain boundaries, isoforms, features, and PDB refs.
   - Scope by organism ID when the target exists across species.

4. Select a structure with `rcsb_search`.
   - Prefer relevant experimental structures with good resolution and the right
     biological assembly.
   - Identify the actual chain IDs and residue numbering in the downloaded file.
   - Keep ligand/cofactor/context chains when they define the binding site.

5. Prepare the target structure.
   - Use `inspect_structure` on the downloaded/prepared file before writing
     contigs or hotspots.
   - Extract the intended target chain, monomer, or minimal biological context.
   - Handle HETATM records, chromophores, modified residues, cofactors, and
     post-translational modifications intentionally.
   - Identify and document gaps and continuous residue ranges.
   - Use PDB format when strict column validation matters, or CIF when the
     downstream tool accepts it directly.
   - Verify every hotspot residue is present in the prepared file.

6. Build the RFD3 binder contig.
   - Inspect the target file before writing the contig.
   - Use the binder pattern: `<binder_length>,/0,<target_chain_start-end>`.
   - Example: `70-110,/0,A1-240`.
   - Put epitope/interface residues in `hotspot_residues`, not in the contig.
   - Include only target chains/ranges needed for binding context.

7. Run `rfd3_design` for backbone generation.
   - Skip this step and produce a design plan if no target structure/contig is
     ready or local compute has not been set up.
   - Start with `num_designs=1-4` and lower `num_timesteps` for input/debug
     validation.
   - First real round: use `num_designs=8-32`, `num_timesteps=100-200`, and the
     most defensible contig/hotspot set.
   - Scale only after the input spec passes validation and outputs look sane.

8. Run `protein_mpnn_design` on promising backbones.
   - Use `ligand_mpnn` if ligand, ion, DNA/RNA, or atom context matters.
   - Fix residues that must remain unchanged.
   - Sample multiple sequences for each backbone. Start around
     `temperature=0.1`; increase to `0.2-0.3` when diversity is too low.

9. Run `esmfold_predict` for sequence-level triage.
   - Do not call ESMFold without a concrete amino-acid sequence or FASTA file.
   - Start with `num_recycles=4`.
   - Reject candidates with low-confidence cores, broken topology, or weak
     confidence in the interface/motif region.

10. Predict promising binder-target complexes with
    `alphafold2_multimer_predict` when an AlphaFold2/ColabFold multimer image
    is configured.
   - Use the designed binder sequence plus the target sequence.
   - Start with a small candidate set; complex prediction is expensive.
   - Treat AF2/Multimer outputs as computational triage, not measured affinity.

11. Rank candidates and choose the next round.
   - Keep a short candidate table with backbone path, sequence path, key
     parameters, fold confidence, observed problems, and decision.
   - Call the current winner "best computational candidate", not "validated
     binder".
   - Preserve diversity: keep the top few candidates from distinct contig,
     hotspot, length, or temperature settings.

## Iteration Strategy

Treat binder design as a campaign. Do not keep rerunning the same settings
unless the previous run failed for infrastructure reasons.

Recommended first campaign:

1. Round 0: debug one tiny RFD3 job.
2. Round 1: baseline design using literature/structure-derived hotspots.
3. Round 2: vary binder length and hotspot set.
4. Round 3: tune `guide_scale` and `num_timesteps` around the best Round 1/2
   settings.
5. Round 4: use ProteinMPNN temperature sweep on the best backbones.
6. Round 5: fold the best sequence variants with higher `num_recycles`, then
   report top candidates and remaining validation gaps.

Parameter tweaks by failure mode:

- Bad or invalid RFD3 inputs: re-check chain IDs, residue numbering, contig
  format, and `target_pdb_path`; do not tune model parameters yet.
- No plausible interface: revise `hotspot_residues`, include the correct target
  chain/range context, try a longer binder, or modestly increase `guide_scale`.
- Low diversity: broaden binder length range, use alternative hotspot subsets,
  or increase ProteinMPNN temperature.
- Low ESMFold confidence in the binder core: try shorter/tighter backbones,
  lower ProteinMPNN temperature, or generate a fresh RFD3 batch.
- Good fold but uncertain interface: keep as a candidate, but run another RFD3
  round with more explicit hotspots or target context.
- Repeated failures across rounds: stop and explain the likely blocker instead
  of spending more compute blindly.

Suggested initial parameter ranges:

- Binder length: `50-90` for small epitopes, `70-120` for general binders,
  `100-160` when a larger surface or scaffold is needed.
- `guide_scale`: start near `1.5`; explore `1.0-2.5` in later rounds.
- `num_timesteps`: `25-50` for debug, `100-200` for real candidates.
- `num_designs`: `1-4` for debug, `8-32` for exploration, larger only after
  the workflow is producing usable candidates.
- ESMFold `num_recycles`: `4` for triage, `8-12` for finalists if runtime is
  acceptable.

## Candidate Ranking

Rank by a transparent rubric. Prefer candidates that satisfy all of these:

- Target structure and residue numbering were verified.
- RFD3 generated a complete binder-target model without obvious geometry
  problems.
- Hotspots/epitope are represented in the design setup.
- ProteinMPNN produced diverse sequences without obvious forbidden motifs.
- ESMFold shows a confident binder core and no broken topology.
- AF2/Multimer complex predictions, when available, place the binder on the
  intended target surface without obvious detachment or collapse.
- Candidate is not merely the top score from one run; it survives at least one
  reasonable parameter perturbation or has close variants.

ESMFold alone does not prove binding because it folds sequences, not binding
affinity. AF2/Multimer complex prediction is stronger interface triage, but it
still does not prove affinity. Recommend downstream validation such as docking,
MD, orthogonal scoring, or wet-lab testing.

## Tool Independence Rule

Do not assume one tool automatically calls the next. The agent must decide and
call each tool explicitly:

- `pubmed_search` does not call UniProt, RCSB, RFD3, MPNN, or ESMFold.
- `uniprot_search` does not call RCSB or download structures.
- `rcsb_search` can optionally download structures, but it does not run RFD3.
- `rfd3_design` generates backbones only; it does not design sequences.
- `protein_mpnn_design` designs sequences only; it does not fold them.
- `esmfold_predict` folds sequences only; it does not redesign failed candidates.
- `alphafold2_multimer_predict` predicts binder-target complexes only; it does
  not redesign candidates or measure binding affinity.

This separation is deliberate. It keeps each tool testable and lets the user run
partial workflows without paying for unnecessary compute.

## Reporting

When summarizing binder-design results, separate:

- Evidence from literature
- Target/structure assumptions
- RFD3 backbone generation status
- ProteinMPNN sequence design status
- ESMFold confidence
- AF2/Multimer complex prediction status when run
- Remaining experimental or computational validation needed

Never describe a computational binder as experimentally validated unless the user
provided real experimental data proving it.

---
name: rfd3-design
description: Use rfd3_design for RFdiffusion3 backbone generation, including binder, motif scaffold, partial diffusion, free generation, hotspots, and contig construction.
version: 1.0.0
author: ProteinClaw
license: MIT
metadata:
  hermes:
    tags: [protein-design, rfd3, rfdiffusion3, backbone, contigs]
    related_skills: [rcsb-search, inspect-structure, protein-mpnn-design]
---

# RFdiffusion3 Design

Use `rfd3_design` for RFdiffusion3 backbone generation. RFD3 is powerful but
contigs are easy to get wrong; inspect the target structure before designing.

`rfd3_design` assumes the Foundry Docker image is already installed. Do not pull
or build Docker images from this skill. If the image is missing, tell the user
to run `hermes setup tools` and choose Protein Design local compute, or run
`scripts/setup_protein_design_local.sh`.

## Tool Inputs

`rfd3_design` accepts:

- `mode`: `free_generation`, `binder`, `motif_scaffold`, or `partial_diffusion`
- `input_path`: optional existing RFD3 JSON/YAML spec
- `output_name`
- `num_designs`
- `contig`
- `target_pdb_path`
- `hotspot_residues`
- `guide_scale`
- `num_timesteps`

## Contig Derivation Order

1. Identify the mode.
   - `free_generation`: no target; contig is a designed length like `80-120`.
   - `binder`: target is fixed; designed binder chain is placed before or after `/0`.
   - `motif_scaffold`: motif residues are fixed inside a designed scaffold.
   - `partial_diffusion`: start from an input structure and perturb/redesign selected regions.

2. Inspect the target structure before building a contig.
   -Use `rcsb_search` or local file parsing to identify chains, residue
     numbering, missing residues, ligands, and target chain IDs.
   - Use `inspect_structure` for local target files and generated RFD3 outputs.
   - Confirm residue identifiers match the actual file, not paper numbering.
   - Watch for HETATM or modified residues such as chromophores and
     post-translational modifications. They may appear as numbering gaps in
     the polymer chain; split fixed target ranges at real gaps rather than
     pretending the target is continuous.

3. Binder design.
   - Keep the target chain fixed after a chain break.
   - Pattern: `<binder_length>,/0,<target_chain_start-end>`.
   - Example: `70-110,/0,A1-240`.
   - Put hotspots in `hotspot_residues`, not inside `contig`.
   - For gapped targets, stitch actual continuous target ranges with `/0`
     separators or use a prepared target file containing only the intended
     continuous chain context.

4. Motif scaffolding.
   - Place fixed motif residues in the contig and surround them with designed
     segments.
   - Example: `30-50,A45-52,40-70`.
   - Use `/0` only for an intended chain break.

5. Multi-chain or target plus ligand contexts.
   - Preserve chain breaks explicitly with `/0`.
   - Include only chains/ranges needed for conditioning.
   - Do not include the whole biological assembly unless necessary.

6. Validate before running.
   - Every chain/range in `contig` and `hotspot_residues` must exist in
     `target_pdb_path`.
   - Designed segments use bare lengths/ranges with no chain letter.
   - Fixed target/motif residues use chain-prefixed residue ranges.
   - The tool runs RFD3 with `prevalidate_inputs=True`.

## Parameter Guidance

- `num_designs`: use 1-4 for input/debug checks, 8-32 for binder exploration,
  and larger batches only after the contig/hotspot setup is producing usable
  candidates.
- `guide_scale`: defaults around 1.5; higher can improve designability but may
  reduce diversity. For binders, explore roughly 1.0-2.5 around the current
  best settings instead of jumping to extremes.
- `num_timesteps`: default 200; use 25-50 for debugging and 100-200 for real
  binder candidates.
- After RFD3, use `protein_mpnn_design` to design sequences and
  `esmfold_predict` to triage foldability.
- Foundry's `rfd3 design` may also produce default MPNN output directories
  alongside the generated backbones. Treat those as a convenience baseline
  using Foundry defaults; call `protein_mpnn_design` explicitly when you need
  different temperatures, model type, fixed positions, designed chains, or a
  reproducible sequence-design sweep.

## Binder Iteration

For binder campaigns, do not keep rerunning identical RFD3 settings. Tune one
or two variables per round:

- Binder length range when the fold is plausible but the interface is poor.
- `hotspot_residues` when the binder misses the intended epitope.
- Target chain/range context when the design is conditioned on the wrong surface.
- `guide_scale` when designs are either too unconstrained or too repetitive.
- `num_timesteps` when debug runs pass and higher-quality candidates are needed.

Record the contig, hotspots, `guide_scale`, `num_timesteps`, and output path for
each round so later ProteinMPNN/ESMFold results can be traced back to the exact
RFD3 settings.

## Output Notes

RFD3 outputs may remap chains. In many binder runs the designed binder is chain
`A`, while target segments become later chains such as `B`, `C`, or `D`. Check
the generated JSON metadata, especially any `diffused_index_map`, before telling
ProteinMPNN which chain to design.

Foundry output filenames can repeat the requested prefix, for example an
`output_name` of `gfp_binder_r1` may produce files like
`gfp_binder_r1gfp_binder_r1_0_model_0.cif.gz`. Do not hand-type downstream
paths from memory; list or inspect the output directory before passing files to
ProteinMPNN, ESMFold, or interface scoring.

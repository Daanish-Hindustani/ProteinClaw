---
id: enzyme_design
version: 2
name: Enzyme Design
description: Sequence redesign of a fixed enzyme scaffold for stability or activity, preserving catalytic geometry.
applicable_tasks: [enzyme_design]
provenance: human_authored
parent_version: 1
---

## Goal

Improve thermostability, expression yield, or catalytic activity of an enzyme by redesigning the sequence on a fixed backbone while preserving the catalytic residues and their relative geometry.

## Inputs

- `scaffold_pdb` — PDB id (or local path) of the enzyme scaffold.
- `catalytic_residues` — list of residue identifiers that must be fixed (e.g. `["A57", "A102", "A195"]` for a serine-protease triad).
- `objective` — `"stability"`, `"activity"`, or `"both"`.

## Steps

1. **Retrieve scaffold.** Call `rcsb` for the PDB id. Confirm chain and resolution.
2. **Identify mutable positions.** Every residue **not** in `catalytic_residues` and **not** in the immediate first shell of any catalytic residue is a candidate. The first shell is residues whose Cα is within ~6 Å of any catalytic Cα — fixing these prevents drift in active-site geometry.
3. **Redesign sequence.** Call `protein_mpnn` with the scaffold backbone, fixing both catalytic and first-shell positions. Use `sampling_temperature=0.1` for stability-focused redesign; 0.2-0.3 to broaden activity exploration. Generate ≥ 16 candidate sequences.
4. **Predict structures.** Call `alphafold` per sequence. For natural enzymes an MSA improves accuracy; supply one when available, otherwise single-sequence prediction is acceptable for screening.
5. **Verify catalytic geometry.** For each prediction, compute RMSD over the catalytic residues' backbone atoms vs. the scaffold:
   - **Catalytic-residue RMSD ≤ 0.5 Å** is the gate. Designs above 1.0 Å should be rejected outright — the active site has likely shifted.
6. **Score globally.**
   - **pLDDT ≥ 0.85** (higher than binder design — we are preserving a known fold).
   - **Per-residue pLDDT in active site ≥ 0.90.** A confident core is non-negotiable.
7. **Stability proxy.** When ESM2 stability scoring is available, compare the redesigned sequence's pseudo-log-likelihood vs. the wild type; positive Δ suggests improved stability.
8. **Return ranked candidates.** Order by `(active_site_pLDDT, -RMSD, stability_delta)`.

## Common pitfalls

- **Redesigning first-shell residues.** Drives catalytic residue drift; the most common silent failure in this workflow.
- **Single-sequence AF on natural enzymes without sanity checks.** Without an MSA, AF may collapse to an alternative low-energy minimum; always cross-check with Foldseek to ensure the predicted fold matches the scaffold.
- **Optimizing pLDDT alone.** The model can be confidently wrong about an active site — RMSD and per-residue confidence in the active site are the real gates.

## Worked example

> Scaffold: 1XYZ (subtilisin-like). Catalytic triad: A57, A102, A195. Objective: stability.

```text
mutable = scaffold residues - {triad} - {first_shell(triad, 6 Å)}
protein_mpnn (T=0.1) → 16 sequences, fixing catalytic + first shell
alphafold (per sequence) → 16 predictions
filter active_site_pLDDT >= 0.90 and catalytic_rmsd <= 0.5 Å → ~4 survivors
optional ESM2 stability score → keep Δ ≥ 0
rank by active_site_pLDDT desc
```

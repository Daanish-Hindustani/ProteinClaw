---
name: proteinclaw-tool-esmfold
description: ProteinClaw per-tool guidance for esmfold.
---

# Tool skill: `structure.esmfold` — monomer pre-filter

Read this before pipeline **step 6** (monomer pre-filter). It is the
operational detail for the one-line summary in the core skill.

Collect ALL designed sequences from step 5 into one batch (up to 64),
ONE call to `proteinclaw_structure_esmfold` with
`sequences=[...]`.

Each `predictions[i]` has:
- `sequence`
- `pdb_path`
- `confidence` (mean pLDDT, 0-100)
- `per_residue_plddt`
- `num_residues`

**Discard sequences with `confidence` < threshold.** Pick **70** as
the threshold (literature convergence: BindCraft uses 0.7; Bennett
2023 uses 0.8 for the stricter pass; 70 is the lenient triage default
that lets AF2 do the discrimination). Log your choice.

**Don't auto-retry** if discard rate > 50%. Continue with what
survived; the user can rerun with adjusted params.

**Literature pattern to be aware of (not implemented in our wrapper
yet):** Bennett 2023's full pipeline also filters on **Cα RMSD of
predicted monomer to designed backbone** — this is the "high pLDDT but
not the right fold" catch. Mention in your summary if you observe
ESMFold passes that look structurally diverged from RFD3 outputs.

## Learned (run fffe79f7c846, 2026-05-26): high ESM pLDDT on low-complexity/poly-Ala MPNN sequences are AF2 false positives — deprioritize, don't promote
With vanilla ProteinMPNN weights at temp 0.1, some backbones yield very Ala-rich/low-complexity
sequences (e.g. `LAAAAAAAVAAAAAELGPAGL...`). These scored the HIGHEST monomer pLDDT in the batch
(85-87) because ESMFold confidently folds regular poly-Ala helices — yet in AF2-multimer the
binder chain pLDDT *collapsed* to ~58 and ipSAE ~0.01 (no specific interface). So a high ESM
pLDDT from a low-complexity sequence is the classic "ESM noise" trap, not a strong candidate.
**Triage rule:** when ranking ESM survivors for the (expensive) AF2 round, down-weight sequences
with low compositional complexity / long Ala runs even if their pLDDT tops the batch; spend AF2
budget on natural-looking sequences instead. This is the sequence-space analogue of the Cα-RMSD
"high pLDDT but wrong fold" catch already noted above. Generalizes to any vanilla-MPNN run until
the wrapper exposes `soluble_mpnn`.

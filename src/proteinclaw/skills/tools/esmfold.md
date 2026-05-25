# Tool skill: `structure.esmfold` — monomer pre-filter

Read this before pipeline **step 6** (monomer pre-filter). It is the
operational detail for the one-line summary in the core skill.

Collect ALL designed sequences from step 5 into one batch (up to 64),
ONE call to `mcp__proteinclaw_tools__structure_esmfold` with
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

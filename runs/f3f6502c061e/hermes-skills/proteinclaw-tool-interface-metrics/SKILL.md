---
name: proteinclaw-tool-interface-metrics
description: ProteinClaw workflow and tool guidance seeded from the repository.
source: /home/ubuntu/ProteinClaw/src/proteinclaw/skills/tools/interface_metrics.md
---

# Tool skill: `analysis.interface_metrics` — deterministic interface QC

Read this before calling `analysis.interface_metrics` (post-AF2, when evaluating
candidates). It runs **in-process** (biopython, no GPU) on a complex PDB path.

`mcp__proteinclaw_tools__analysis_interface_metrics`:
- `complex_pdb_path` — the AF2 complex PDB (binder = chain A, target = chain B).
  Use the host path from the AF2 envelope's `complex_pdb_path`.
- `hotspot_residues` — the **same** hotspots you gave RFdiffusion3 (e.g. `"A56,A115"`),
  in the **original target numbering**.
- `crop_start` — the **first residue number of the target crop** you fed RFD3/AF2
  (e.g. crop `19-127` → `crop_start=19`). REQUIRED for correct hotspot satisfaction,
  because ColabFold usually **renumbers the AF2 target chain from 1** — the tool maps
  `orig → orig − crop_start + 1`. Omit only if you know the target isn't renumbered.
- `binder_chain`/`target_chain` default to `A`/`B` (the AF2 convention) — don't override
  unless a tool reported a different layout.

## What it returns (all from the predicted complex geometry)
- `interface_contacts` — # residue pairs with heavy atoms ≤ 4.5 Å across the interface.
- `interface_residues_binder` / `interface_residues_target` — interface size per side.
- `interface_bsa` — buried surface area (Å², ΔSASA via Shrake-Rupley). A real mini-binder
  interface buries **≳ 600 Å²**; well below that = a thin/unconvincing interface.
- `clash_score` — steric clashes per 1000 atoms, MolProbity-style (approximate, DIY — not
  phenix-exact; no explicit H). Excludes disulfides and applies an H-bond/salt-bridge
  allowance for N/O pairs, so it counts genuine sub-VdW overlaps. Lower is better; designed/
  predicted structures run higher than crystals — treat it as a relative signal, not an
  absolute MolProbity clashscore.
- `contact_geometry` — interface residue counts + binder↔target interface COM distance.
- `hotspot_satisfaction` — fraction (0–1) of your hotspots the binder actually contacts
  (Cβ ≤ 8 Å or heavy ≤ 5 Å). **`null`** means hotspots didn't map onto the target chain
  (check `crop_start`) — read `notes` and `hotspot_detail`.

## How to weigh it (QC, not ranking)
These **augment** the `complex_confidence` + ipSAE ranking; they do **not** replace it,
and there is deliberately **no KD/affinity estimate** (untrustworthy from a single
predicted designed complex). A strong candidate has: high `hotspot_satisfaction` (the
binder hit the epitope you aimed at — low means it drifted, revisit hotspots), BSA
≳ 600 Å², and a low clash score, **on top of** good complex pLDDT + ipSAE. Use a low
hotspot satisfaction as a signal to re-task hotspots in the next round.

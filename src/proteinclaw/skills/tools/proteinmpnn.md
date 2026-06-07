# Tool skill: `design.proteinmpnn` — sequence design

Read this before pipeline **step 5** (sequence design). It is the
operational detail for the one-line summary in the core skill.

For each RFD3 design path:

`mcp__proteinclaw_tools__design_proteinmpnn`:
- `backbone_pdb=<path from RFD3>`
- `chain_id=<output_binder_chain from RFD3>` — freezes target.
- `sampling_temp=0.1` (round 1 default; Bennett 2023 / dl_binder_design /
  BindCraft / ProteinDJ all use 0.1). Raise to **0.2-0.3** in round
  2 if you want sequence-level diversity on a confirmed backbone.
- `num_sequences`: **you decide, paired with your RFD3 choice**.
  The total funnel width is `num_designs × num_sequences` — that's
  how many AF2 jobs you'll run. Heuristics:
  * **Easy target, round 1**: 4 seq/backbone (4×4 = 16 AF2 jobs)
  * **Hard target, round 1**: 8 seq/backbone (8–12 × 8 = 64–96 AF2 jobs)
  * **Round 2 refinement on confirmed backbones**: 8 seq/backbone at
    `sampling_temp=0.2–0.3` for sequence diversity.
  Same "anti-pattern" rule as `num_designs`: don't blindly pick the
  YAML default (8). State your rationale in the narration before the
  MPNN call.

**`use_soluble_model` (prefer this for binders).** The literature
consensus is that **`soluble_mpnn`** is the right default for de novo
binders (reduces apolar exposed residues, better solubility/
monodispersity — Bennett 2023, BindCraft). Set `use_soluble_model=true`
on your MPNN call for binder design; it works with any `model_name`
(default `v_48_020` is fine). The vanilla weights remain the default
(`use_soluble_model=false`) for non-binder/general inverse-folding use.

Result: `result.sequences[]` (list of designed sequences) and
`result.designs[*].score` (lower = better backbone-sequence match).
**MPNN score is a tiebreaker, not a hard filter** — AF2 dominates.

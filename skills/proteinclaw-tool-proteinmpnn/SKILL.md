---
name: proteinclaw-tool-proteinmpnn
description: ProteinClaw per-tool guidance for proteinmpnn.
---

# Tool skill: `design.proteinmpnn` — sequence design

Read this before pipeline **step 5** (sequence design). It is the
operational detail for the one-line summary in the core skill.

MCP name: `proteinclaw_design_proteinmpnn`. This is an inverse-folding step:
it designs amino-acid sequences for an RFD3 binder backbone while keeping the
target fixed. It does not decide whether the interface is real; AF2-multimer
and interface metrics decide that later.

## Inputs

For each RFD3 design path:

`proteinclaw_design_proteinmpnn`:
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
- `seed`: set when reproducibility matters across reruns.
- `fixed_positions` / omitted positions, if exposed by the active schema:
  use only when the user or RFD3 design requires preserving specific residues.
  Do not freeze large regions by default; it reduces sequence search.

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

## What To Record

Append to `plan.md`:

- Which RFD3 backbone(s) were sequenced.
- `sampling_temp`, `num_sequences`, and whether soluble weights were used.
- Total downstream AF2 jobs implied by `backbones x sequences`.
- Any sequence filters you apply before ESMFold: extreme length mismatch,
  invalid residues, obvious low complexity, or long poly-Ala/poly-Gly runs.

## Triage Before ESMFold

Do not throw away diversity solely because an MPNN score is not rank 1. Keep a
small spread of good-scoring sequences per backbone when compute allows. Prefer
natural-looking sequences over low-complexity sequences even if the low-complexity
sequence has a superficially good MPNN score; those often fold as generic helices
and fail AF2 interface metrics.

## Failure Handling

- If the tool fails because the binder chain is missing, inspect the RFD3 output
  with `proteinclaw_data_pdb_analyze` or a short run-local scratch check, then
  retry once with the correct `chain_id`.
- If Docker/GPU execution fails, record the structured error and drop that
  backbone after one adjusted retry.
- If all sequences from one backbone are pathological, do not spend AF2 budget on
  that branch. Either choose a different RFD3 backbone or refine the design
  hypothesis.

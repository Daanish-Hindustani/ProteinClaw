# Tool skill: `design.rfdiffusion3` — backbone generation

Read this before pipeline **step 4** (backbone generation). It is the
operational detail for the one-line summary in the core skill.

`mcp__proteinclaw_tools__design_rfdiffusion3`:
- `target_pdb`, `target_chain`, `hotspot_residues` (from step 3)
- `binder_length`: range e.g. `"60-80"`
- `num_designs`: **you decide — see "Sizing the funnel" below**. The
  YAML default of 4 is a smoke-test value, not a guideline. Range
  1–32; agent must reason about target difficulty and round budget
  rather than copy the default.
- `num_timesteps=50` default — well-tested, don't raise.
- `step_scale=3`, `gamma_0=0.2`, `is_non_loopy=true` are the
  RFD3 PPI tutorial canon. Don't touch unless the user asks for
  diversity over designability.

## Partial diffusion — round-2 refinement of a proven backbone

Two **mutually exclusive** ways to call this tool:
- **De-novo (cold start):** `target_pdb` + `hotspot_residues` + `binder_length`
  (the params above). Use in round 1.
- **Partial diffusion (refine a winner):** `start_pdb` + `partial_t`. Use in
  round 2+ once you have a docking backbone worth polishing — it's the
  highest-impact refinement (5–10× hit-rate on hard targets).

Partial-diffusion params:
- `start_pdb`: path under `/workspace` to a prior **binder+target complex**
  PDB — the best AF2 winner from a previous round (chain A = binder,
  chain B = target by our convention).
- `partial_t`: **Angstroms of noise** to add before re-denoising (RFD3 caps
  at 15). **2–6 Å = polish** (stay near the winner), **8–12 Å = explore**.
  It is NOT a timestep count — small means closer to the input.
- `binder_chain` / `target_chain`: chain letters in `start_pdb` (default
  `A` / `B`). `num_designs`, `num_timesteps`, `step_scale`, `gamma_0`,
  `is_non_loopy` still apply.
- **Do NOT pass `binder_length` or `hotspot_residues`** in this mode — the
  geometry comes from `start_pdb`; RFD3 rejects a length arg with partial_t.

RFD3 re-noises the *whole* complex by `partial_t` Å (target included), so for
small `partial_t` the target barely moves; downstream MPNN→ESM→AF2 re-design
and re-score against the clean target sequence anyway. Output is the usual set
of backbone PDBs (binder chain A, target chain B) — feed them to ProteinMPNN
exactly like de-novo outputs.

## Sizing the funnel — how to pick `num_designs` (and downstream `num_sequences`)

There is no single right number. **You are expected to choose it
based on signals available before the run starts.** Reason from these
inputs and state your choice (with one-line justification) in your
narration before the RFD3 call:

1. **Target difficulty signal** (highest weight)
   - Co-crystal binder available, well-modeled hotspot face, no gaps
     in the crop → **easy**: 4–6 backbones is enough to validate the
     pipeline; ramp later if round-1 yields zero hits.
   - Hotspots inferred (no known binder), surface-level epitope, or
     intrinsically-disordered region nearby → **hard**: start at
     **8–12 backbones**, expect to need round 2.
   - Novel target class (GPCR, membrane protein, glycosylated site,
     PDB resolution > 3.0 Å) → **very hard**: 12–16 backbones
     minimum, and warn the user that hit-rate may be low.

2. **Round budget** (`--rounds N`, surfaced in the per-run addendum)
   - `rounds=1`: spend more here — there's no second chance. Bias
     toward the upper end of your difficulty band.
   - `rounds=2+`: smaller round 1 is fine because round 2 will use
     partial-diffusion on round-1 winners (5–10× hit-rate boost,
     core skill "Self-refining loop"). Round 2 typically needs only
     4–8 refined designs.

3. **Compute envelope** (sanity check, not a primary input)
   - Each backbone is 1–3 min RFD3 + 30 s MPNN/seq + 24 s ESM (batched)
     + 5–15 min AF2/sequence. **A single A100 finishes ~6–8 candidates
     through AF2 per hour.** If you plan 12 backbones × 8 sequences =
     96 AF2 jobs, that's ~12–24 h of wall-time. Don't quietly schedule
     that without flagging it in your narration.
   - The Bennett 2023 gold standard used ~10,000 backbones per target.
     We're operating 2–3 orders of magnitude below that — be honest in
     your summary about exploratory vs exhaustive scale.

4. **Stopping criterion as feedback**: the core skill "Self-refining
   loop" defines success as ≥5 designs with `complex_confidence > 75`.
   If round 1 finishes with that already met, do not run round 2.
   If round 1 finishes with zero such designs, round 2 must increase
   `num_designs` *and* shift to partial-diffusion — repeating the same
   numbers will not help.

**Anti-pattern:** picking `num_designs=2` because the YAML default is
4 and "less is faster." If the agent can't justify the number from the
four inputs above, default to **8** (the figure most pipelines —
BindCraft, ProteinDJ, dl_binder_design — converge on for a real round).

**Critical:** read the envelope's `output_binder_chain` and
`output_target_chain`. RFD3 assigns chain IDs by contig order
(typically binder = A, target = B), but the wrapper detects it
empirically — never assume a letter.

**If RFD3 fails with "Residue X not found in atom array":** the crop
spans an unmodeled residue. Pick a different crop range from step 1b's
gap list, OR a different PDB.

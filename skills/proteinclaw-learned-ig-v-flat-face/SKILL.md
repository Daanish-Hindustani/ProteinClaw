---
name: proteinclaw-learned-ig-v-flat-face
description: ProteinClaw learned guidance for IgV and flat beta-sheet target faces.
---

# Learned: IgV Flat-Face Targeting

Use this skill when the target is an Ig-like V domain, checkpoint-style
beta-sandwich, TREM2-like IgSF apex, PD-L1-like front face, or another broad
flat beta-sheet surface.

## Practical Rule

With the current ProteinClaw RFdiffusion3 wrapper, unconditioned alpha-helical
bundle binders are higher yield than generic beta-rich binders on flat IgV
faces. Literature support for beta-strand binders usually assumes explicit
strand conditioning or a design path ProteinClaw does not currently expose.

Do not spend AF2 budget on beta-looking RFD3 outputs just because they have
good ESMFold monomer pLDDT. The common failure mode is "folds by itself, does
not dock the target."

## Hotspot Selection

Prefer sparse, contiguous, physically reachable hotspot sets:

- Pick the deepest hydrophobic or aromatic ridge first.
- Add one charged/polar centering residue only when it is close enough for the
  same binder footprint to reach.
- Avoid asking one helical bundle to satisfy peripheral anchors on opposite
  sides of a flat face.
- For TREM2-like apices, CDR2-ridge-style hydrophobic anchors are often more
  reachable than lateral-face mechanism hotspots.

If a prior or literature epitope is biologically attractive but geometrically
flat and featureless, run at most one bounded attempt. If ipSAE stays below
roughly 0.3 on the top AF2 candidates, pivot rather than grinding.

## Expected Metrics

For unconditioned RFD3 helical binders on IgV apices, a realistic computational
ceiling may be below the strict final gate:

- ipSAE around 0.75-0.85 can be a strong exploratory signal for this class.
- ipTM above 0.85 and complex pLDDT above 93 are expected for credible poses.
- BSA often lands around 1200-1800 A^2 for the successful helical-bundle pose.
- Hotspot satisfaction may plateau at 3-of-4 or similar when the missing hotspot
  sits at the edge of the helical footprint.

Do not quietly lower the global strict gate. Instead, report this as a
target-class ceiling and label candidates as exploratory or experimental
nominees, not strict computational hits.

## Refinement Guidance

- A focused ProteinMPNN refinement on a proven backbone can lift ipSAE/ipTM
  modestly at low cost.
- A single partial-diffusion polish can help when the parent pose is already
  credible.
- Sequential partial-diffusion rounds often plateau on this class; do not assume
  the lift compounds.
- Longer cold-start binders do not automatically solve missed peripheral
  hotspots. If the topology cannot reach the missing residue, length alone is
  not the fix.
- Five-model AF-M confirmation is a robustness filter, not a score-lifter. Use
  it to reject lucky rank-1 outliers.

## When To Escalate

If the user truly needs a flat beta-sheet edge mechanism, call out that the
current ProteinClaw wrapper lacks strand conditioning. Reasonable next methods
would be strand-conditioned RFdiffusion, a different binder topology engine,
AlphaFold3-style reranking, or post-design Rosetta relaxation when those become
available in the tool surface.


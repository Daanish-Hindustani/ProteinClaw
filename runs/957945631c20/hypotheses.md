# Design hypotheses — PD-L1 IgV mini-binders (validation batch)

## Run scope
User request: small, fast **pipeline-validation** batch on a 22 GB GPU.
60–80 aa de novo mini-binders to the IgV domain of human PD-L1.
~3 backbones × ~3 sequences. NOT an exhaustive search. Round budget: 2.

Because the user explicitly scoped this as minimal validation, I ran
**light** due diligence (target resolution + one literature corroboration +
structural reasoning) instead of the full multi-scout debate. Flagged in
the final summary.

## Round 1

### Target resolution
- **PDB 5JDS, chain A** = human PD-L1 ectodomain (UniProt Q9NZQ7, 290 aa).
- Chain A modeled 18–376 with gaps at 133–200 and 203–300 (IgC + linker).
- IgV domain = UniProt 19–127; fully modeled, **no gaps** below res 133.
- **Crop chosen: 18–127** (110 aa, gap-free, ≤130 → fast RFD3, hosts all hotspots).
- Cropped PDB: `gpu-workspace/957945631c20/pdb_fetch_0/5JDS_chainA_crop18-127.pdb`

### Hotspots (3 — within the converged 3–6 consensus)
- **A56 (Tyr), A115 (Met), A123 (Tyr)** — verified residue identities against
  the Q9NZQ7 sequence.
- Rationale: all three sit on the **GFCC'C'' front β-sheet face** of the IgV
  domain, which the PD-1/PD-L1 co-crystals (3BIK, 4ZQK, 3SBW) identify as the
  primary PD-1 interface (lit_search: PMC3148082 "PD-1 binds the upper part of
  the GFCC'C'' face of the IgV domain of PD-L1"; PMC12679730; PMC8980021 maps
  PD-1 + atezolizumab contacts onto the same IgV surface).
- This is exactly the hotspot set in RFD3's official PD-L1 PPI example and the
  set this repo's prior RFD3 E2E used successfully (NOTES 2026-05-23).
- Hotspot atoms (side-chain representative): A56 Tyr→CG,OH; A115 Met→CG,SD;
  A123 Tyr→CG,OH.

### Binder length
- 60–80 aa mini-binder window (user-specified; squarely in the canonical
  de novo PPI sweet spot 60–100).

### Funnel sizing (validation, not search)
- RFD3 num_designs = **3** (user-specified ~3 backbones; easy, well-modeled,
  co-crystal-backed target → small batch is appropriate for validation).
- MPNN num_sequences = **3/backbone** (user-specified) → 9 AF2 jobs.
- num_timesteps = **50** (skill: well-tested for PPI, ~4× faster than the
  200 default — fits the "small, fast" goal).
- step_scale=3, gamma_0=0.2, is_non_loopy=true (PPI canon defaults).
- MPNN sampling_temp=0.1 (round-1 conservative, high-confidence).
- ESMFold triage cut: pLDDT ≥ 70 (lenient triage; AF2 does discrimination).

### Quality gate
≥5 designs with complex_confidence > 75. With only 9 AF2 jobs this is a
*validation* run — gate may not be reachable at this scale; goal is a clean
end-to-end pass with a sensible rank table, and to confirm the funnel works.

# Run plan — TREM2 binder design (PDB 5ELI)

## Target
- **PDB:** 5ELI (apo human TREM2 ectodomain, 2 chains in asu — dimer packing)
- **Chain:** A
- **Crop:** 20-131 (112 aa, ordered IgV-like ligand-binding ectodomain; gap 132-200 is unmodeled stalk)
- **UniProt:** Q9NZC2, 230 aa total; Ig-like V-type 29-112
- **Fold class:** Ig-like V-type (apex CDR-like loops + flat β-sandwich faces)
- **Sequence constraint:** binder ≤ 250 aa → use 70-90 aa mini-binder

## Literature (round 1 due diligence)
Three TREM2 surfaces (PMC12996653, PMC11721465):
1. **Apex CDR-like loops** — hydrophobic + central R47, binds Aβ/ApoE (designable face; AD-risk R47H here)
2. **Lateral basic patch** — IL-34
3. **Opposite face** — multimerization
Canonical residues: R47 (PMC6716448, PMC5767550), W44/R46 (CDR1), H67/L71/F74/R76 (CDR2), R98/H103 (CDR3).

## Structural sandbox (biopython SASA, scratch/sandbox.py)
Apex residues, high SASA, clustered on CDR-like face:
- W44 (132 Å²), R47 (72 Å²), L71 (143 Å²), F74 (124 Å²), R76 (149 Å²), R98 (144 Å²).
All on chain A inside crop 20-131; no gaps spanned.

## Learned skills consulted
- `learned/ig-v-flat-face.md`: TREM2 is Ig-V; expect α-helical-bundle hits to dominate; sparse hotspots (≤5) sufficient.
- `learned/target-resolution.md`: crop verified 878 ATOM, 0 HETATM.

## Round 1 hypothesis
- **Hotspots:** A44, A47, A74, A76, A98 (5 sparse anchors across CDR1/2/3, aromatic+hydrophobic+basic mix)
- **Hotspot atoms:** W44 CD2,NE1 ; R47 CZ,NH1 ; F74 CG,CZ ; R76 CZ,NH1 ; R98 CZ,NH1
- **Binder length:** 70-90 aa
- **RFD3:** num_designs=8, PPI defaults
- **MPNN:** num_sequences=4, sampling_temp=0.1 → 32 sequences
- **ESM:** pLDDT > 70 cutoff
- **AF2-multimer:** colabfold MSA, num_models=1, target = crop seq

## Quality gate
complex pLDDT > 93 AND ipsae ≥ 0.93 AND iptm ≥ 0.7 AND hotspot satisfaction ≥ 0.70 AND BSA ≳ 700 Å². Target ≥3 hits.

## Budget
Up to 4 rounds.

---

## Round 1 budget check: round 1 of 4

### Round 1 — pipeline: RFD3 (8 backbones) → MPNN temp 0.2 (4 seq each = 32) → ESM > 70 (25 survivors) → AF2 (10 picks)
Top 3 (by complex_confidence): seq#30 (BB7, pLDDT 97.0/ipSAE 0.66/ipTM 0.79), seq#31 (BB7, 96.4/0.72/0.85),
seq#17 (BB4, 91.9/0.52/0.74). Interface metrics: best BSA = 1626 Å² (seq#17), best hotspot
satisfaction = 60% (seq#17 — covers A44/A74/A76, misses A47/A98). BB7 α-helical-bundle dominates as
the IgV-flat-face learned rule predicted.
**Gate verdict:** no design clears strict gate (ipSAE ≥ 0.93, hotspot sat ≥ 0.70). All near-hits
satisfy CDR2 hotspots only; R47 sits 10-12 Å away from the closest binder side chain.

## Round 2 budget check: round 2 of 4
Hypothesis: re-MPNN winning backbones (BB4, BB7) at temp 0.25 for sequence diversification on a
docking-proven backbone (cheapest refinement available; wrapper does not expose partial diffusion).
12 new sequences → ESM (all 6 picked clear 70) → AF2.
**Result:** new best = MERLRRLAREMRAALAADDDAAAAAVCVEAGRLFFAEGRPEAALEAYREALRLNPDNADARAGLAAAEAAL
(BB7 round 2, step 29): pLDDT 96.74, ipSAE 0.753, ipTM 0.86, pDockQ2 0.87, BSA 1396 Å², hotspot 60%.
Improvement vs round 1: +0.04 ipSAE, +0.01 ipTM, +0.05 pDockQ2 — same backbone family, real but
modest. Miss pattern unchanged: A74/A76 satisfied, A47/A98 still 10+ Å from binder. Captured this
as a learned skill (see `learned/ig-v-flat-face.md`, run adbe5874aeb4 block).

**Final gate verdict:** zero strict-gate hits. Top 3 are *strong sub-strict* candidates —
complex pLDDT and ipTM clear the bar; ipSAE 0.66-0.75 and hotspot satisfaction 60% sit below it.
Honest classification: high-quality docked predictions on the CDR2 sub-epitope of TREM2's apex,
not full apex coverage.

**Stopping early at round 2 of 4:** rounds 3-4 cannot meaningfully change the geometric constraint
(binder's helix ends cannot simultaneously reach R47 + R98 from a CDR2-anchored pose at 71 aa). The
right refinement is structural (longer binder ≥100 aa with a second helix or loop reaching R47),
which is a different design hypothesis worth a separate run. Delivering round-2 winners now.


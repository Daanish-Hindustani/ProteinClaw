# Run plan & reasoning

**Target:** human μ-opioid receptor (MOR / OPRM1), UniProt **P35372** (400 aa). Class-A GPCR, 7-TM.

**Workflow:** nanobody (VHH library + AF2-multimer scoring). Budget = 2 hypothesis cycles.

## Target resolution & cropping (Cardinal: crop ECL face!)

Prior MOR nanobody run `48045e097ad0` failed 0/10 because it passed the full 7-TM span; AF2-without-lipid docked nanobodies into the hydrophobic TM bundle → interpenetrating poses (BSA 2300-3300, clash 50-252). The skill now mandates cropping to the extracellular face + hotspots. Following that.

**Crop choice (round 1):** residues **195-235** (41 aa, MOR ECL2 + minimal TM4/TM5 flanks) =
`ILSSAIGLPVMFMATTKYRQGSIDCTLTFSHPTWYWENLLK`

Rationale: ECL2 is the longest and most accessible loop in MOR, anchored by the conserved C140-C219 disulfide; it forms the binding-pocket "lid" and is the canonical extracellular epitope for GPCR nanobodies. A 41-aa peptide-style construct presents the ECL2 surface without the membrane-buried TM bundle. crop_start = 195.

**Epitope hotspots:** `B211,B214,B230` — K211, Q214, W230 are surface-exposed ECL2 residues (charged + aromatic — typical paratope-magnet residues for VHH CDRs).

## Round 1 hypothesis

- Library: 80 VHHs on h-NbBCII10 framework (FR2 tetrad preserved), CDR3 9-18 aa.
- ESMFold monomer prefilter @ pLDDT ≥ 70 (drops misfolded scaffolds).
- AF2-multimer each survivor vs ECL2 41mer (binder chain A, target chain B).
- Triage by `complex_confidence`, gate metrics on top-K, predicted KD advisory.
- Nanobody gate: complex_pLDDT > 85 AND ipsae ≥ 0.6 AND iptm ≥ 0.6 AND interface_plddt ≥ 87 AND h3_plddt ≥ 86 AND cdr_contact_fraction ≥ 0.70 AND 600 ≤ BSA ≤ 1400 AND clash ≤ 50.

If gate unmet → round 2 with a structural pivot (different epitope or wider CDR3 range or library 2×).

Budget check: round 1 of 2.

## Round 1 outcome (4 of 12 AF2 calls)

Tested nb_0038, nb_0008, nb_0013, nb_0076 against ECL2 41mer.

- complex_confidence: 82.7–87.0 ✓ (binders fold)
- **target_chain_plddt: 34–38 ✗** (peptide is disordered in isolation)
- **ipSAE: 0.016–0.017 ✗ (gate ≥0.6)**
- ipTM: 0.24–0.27 ✗ (gate ≥0.6)
- pdockq/pdockq2/lis: all near zero → no real interface

**Worked:** Library generation, ESMFold prefilter, AF2 pipeline are healthy; binders fold confidently.
**Why:** AF2 modelled the 41-aa ECL2 peptide as a fully disordered chain. The conserved class-A disulfide (C142 in TM3 ↔ C219 in ECL2) gives ECL2 its native β-hairpin scaffold; the round-1 crop included C219 but NOT C142, so AF2 had no constraint to fold the loop. With a floppy target, no nanobody can form a high-confidence interface.
**Gap:** Target lacks a defined conformation for binder to dock onto. Cropping problem, not a binder-quality problem.
**Next hypothesis:** Extend the crop to include BOTH disulfide cysteines so AF2 forms the C142–C219 bond and ECL2 adopts its β-hairpin fold. This adds a small TM3-end stretch — risk of the membrane-in-vacuum artifact remains but is bounded (a single TM-end helix is not the full bundle that doomed run `48045e097ad0`). Stopping round 1 early after 4 confirming evidence calls — no point burning the other 8.

## Round 2 hypothesis

- **Target crop:** residues **138-235** (98 aa, contains C142 + C219 → disulfide can form → ECL2 β-hairpin scaffold). crop_start = 138.
- Sequence: `GTILCKIVISIDYYNMFTSIFTLCTMSVDRYIAVCHPVKALDFRTPRNAKIINVCNWILSSAIGLPVMFMATTKYRQGSIDCTLTFSHPTWYWENLLK`
- **Hotspots:** `B211,B214,B219,B230` — same ECL2 face plus C219 disulfide anchor.
- Reuse top-8 VHHs from round 1 ESM ranking (binders are unchanged — no need to regenerate library).
- Watch BSA and clash carefully: with a TM3-end stretch present, AF2 may still attempt non-physical packing. Reject any BSA > 1400 or clash > 50 (gate enforces).

Budget check: round 2 of 2.

## Round 2 outcome (4 AF2 calls + interface metrics on top 2)

- complex_confidence: 78.1–83.7 ✓
- target_chain_plddt: 47–57 (better than R1's ~36 — disulfide does stabilize ECL2 some)
- **ipSAE: 0.000–0.013 ✗** (gate ≥0.6 — orders of magnitude off)
- iptm: 0.17–0.25 ✗
- Interface QC on top two: **hotspot_satisfaction = 0%** (binders 25–43 Å from intended hotspots), clash 62–78 ✗ (gate ≤50), BSA 1062–1352 (borderline). Binders dock onto the TM stretch, not the ECL2 vestibule — the bounded version of the membrane-in-vacuum artifact.

**Worked:** Better target conformation (longer crop + disulfide). Pipeline + gate machinery correctly flag every failure mode.
**Why no hits:** Library is 80 sequences; the paper uses ~10⁴ and reports nM hit rates ~0.01–1%. Expected hits at N=80 ≈ 0. Compounded by the TM-end stretch in the crop pulling binders off-target despite hotspot intent.
**Gap:** Library size + target representation. The combinatorial CDR-diversification space is huge; randomly sampling 80 sequences with no positional priors will almost never land near a real paratope.
**Next (out of budget for this run):**
1. **Scale library 100× (8 000–10 000 VHHs)** — paper-aligned scale; biggest single ROI move.
2. **Or supply a curated VHH library via `external_fasta`** (immune-repertoire / VHH database) — drastically narrows the search to plausible paratopes.
3. **Better target representation:** start from a real MOR cryo-EM PDB (e.g. 8E0G, active state) rather than a sequence crop — extract the extracellular face with disulfides intact.
4. Pair with a structurally-distinct sub-epitope (e.g. ECL1 or N-term cap) as a second target to diversify hypotheses.

## Final result: 0/8 hits clear the strict nanobody gate.

This is the **honest, expected** outcome for an ~80-member combinatorial VHH library against a GPCR extracellular face. The pipeline produced clean diagnostic signal (binders fold; gate enforces clash/BSA bounds; hotspot satisfaction confirms off-target docking) and avoided the previous-run failure mode (interpenetrating 7-TM docks). Scaling the library is the next move.



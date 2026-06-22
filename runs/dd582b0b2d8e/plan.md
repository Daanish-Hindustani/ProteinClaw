# Run plan & reasoning — MOR ECL2 nanobody screen

## Target resolution
- UniProt **P35372** (human μ-opioid receptor, MOR/OPRM1), 400 aa.
- Class-A GPCR, 7-TM. Following the cardinal "crop to extracellular face" rule.
- **Crop: residues 138–235 (98 aa)** — `crop_start = 138`.
  - Contains both ECL2 disulfide cysteines **C142** (top of TM3) and **C219** (mid-ECL2), so ECL2 folds with its native disulfide constraint.
  - Spans TM3 top → ECL2 → top of TM5; covers the orthosteric vestibule lid.
  - Crop sequence: `GTILCKIVISIDYYNMFTSIFTLCTMSVDRYIAVCHPVKALDFRTPRNAKIINVCNWILSSAIGLPVMFMATTKYRQGSIDCTLTFSHPTWYWENLLK`
- This crop is validated from prior MOR runs (see skill cardinal rule).

## Epitope hotspots (ECL2 face, original P35372 numbering)
Picked surface-exposed ECL2 residues at and around the vestibule entry:
- **K209** (ECL2 N-term entry)
- **D218** (right next to the C219 disulfide stem)
- **T220, F223** (ECL2 loop surface)
- **H225** (extracellular face)
- **W229** (top of TM5, lines the vestibule)

Hotspot string: `BK209,BD218,BT220,BF223,BH225,BW229` — passed to interface_metrics with `crop_start=138`.

## Library
- **Natural VHH repertoire** at `/home/ubuntu/ProteinClaw/data/natural_vhh_repertoire.fasta` (300 sequences), passed verbatim via `external_fasta` — no random library generation. CDR ranges will be null (no ANARCI) so cdr-aware metrics degrade to null; we judge on `complex_confidence`, `ipsae`, `iptm`, `interface_bsa`, `clash_score`, `hotspot_satisfaction`.

## Pipeline (Round 1)
1. `design.nanobody_library` with `external_fasta` → write library.fasta to session.
2. `structure.esmfold` on all 300 — discard pLDDT < 70 (per esmfold skill).
3. `structure.alphafold2_multimer` on each survivor vs the MOR ECL2 crop.
4. `analysis.interface_metrics` per design with crop_start=138 + ECL2 hotspots.
5. Triage on the strict nanobody gate.

## Round 1 — Worked / Why / Gap / Next

**Worked:** Library + ESM prefilter executed cleanly. 300 natural VHHs all CDR-numbered. 20 AF2-multimer complexes ran successfully (target ECL2 crop folded as a partial helix bundle, target pLDDT 49-64; binder chain pLDDT 82-90 — VHHs themselves fold fine).

**Why (the result):** Of 20 AF2-multimer runs across the top ESM-confidence VHHs (filter: pLDDT ≥79, CDR3 ≥8), **0 designs cleared the nanobody gate**. Best metrics:
- top ipSAE = **0.018** (nb_0273), needs ≥0.6
- top iptm = **0.34** (nb_0271), needs ≥0.6
- ipSAE was 0.000 for 11/20 designs (no AF2-detected interface signal at all)

**Gap (why we missed):** Two compounding issues:
1. The ECL2 crop (98 aa, residues 138-235) folds with **moderate disorder** in AF2-multimer (target chain pLDDT 49-64). The TM3 cytoplasmic end / disulfide pairing without the full TM bundle is harder than expected. A receptor with looser ECL2 conformation gives AF2 less to dock against.
2. The natural VHH repertoire was raised against many unrelated targets — base rate of "incidental MOR ECL2 binder" in a 300-member random pool is essentially zero. ESMFold pre-filter selects for monomer foldability, not target affinity. We screened the brightest monomers and still got 0 hits.

**Next (Round 2 hypothesis):** Pivot to a **CDR3-length / origin-stratified deep sample** that we previously down-sampled by ESM pLDDT. Hypothesis: ESM monomer pLDDT is essentially uncorrelated with MOR binding; we should sample **camelid-origin VHHs with long CDR3 (15-22 aa)** from the ESM 70-79 band that we previously skipped — long-CDR3 VHHs have the largest paratope reach into the ECL2 vestibule and the highest incidental-binding rate. This is a structural pivot (different selection axis = CDR3 reach, not monomer confidence), not "more of the same." Run ~12 additional AF2 complexes.

If Round 2 also fails the gate (≥3 hits), the honest conclusion is: a 300-member natural VHH repertoire is too small to incidentally contain a MOR ECL2 binder. The paper's success used a 10⁴ library — we have 300. Report that limitation honestly.

---

## Round 2 — Worked / Why / Gap / Next
_To be filled._

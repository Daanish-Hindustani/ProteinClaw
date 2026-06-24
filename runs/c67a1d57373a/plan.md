# Run plan & reasoning — μ-opioid receptor (MOR) nanobody campaign

## Target

**μ-opioid receptor (MOR / OPRM1, UniProt P35372)** — a Class-A GPCR, the
primary molecular target for clinical opioid analgesics (morphine, fentanyl).
Therapeutic relevance: a high-affinity nanobody to the extracellular face of
MOR could (a) act as a biased modulator (allosteric agonist/PAM/NAM at the
orthosteric vestibule), (b) be developed into bivalent / opioid-conjugate
diagnostics, or (c) serve as a chemical probe of receptor state. Active-state
extracellular surface is the classical "vestibule" rim around ECL2.

## Critical lesson from the prior MOR run (run 48045e097ad0, NOTES.md 2026-06-21)

The previous attempt at this exact target **scored 0/10**. Root cause: the
agent passed the **full MOR[65-345] 7-TM span** as the AF2 target with no
epitope crop and no hotspots. Without lipid, AF2 docks the nanobody onto the
hydrophobic TM bundle (normally buried in membrane) → BSA 2300-3300 Å²,
clash 50-252, ipSAE ≈ 0 — the unmistakable "interpenetrating crammed pose"
signature. The skill has since been hardened to mandate cropping to the
extracellular face + setting epitope hotspots. **I will follow that
guidance verbatim.**

## Strategy

1. Resolve MOR target: UniProt P35372 (human) for sequence + topology;
   RCSB for a high-resolution active-state structure (5C1M / 8EF5 / 8EFB).
2. **Crop to the extracellular vestibule** — a single contiguous span that
   contains the ECL2 β-hairpin lid (the orthosteric pocket cap, anchored by
   the Cys128-Cys217 disulfide), plus its TM-helix anchors. Target crop
   size ≈ 80-130 residues — enough TM context that ECL2 folds correctly,
   small enough that AF2 cannot drift to the intracellular face.
3. Set epitope hotspots on the ECL2 lid (residues in the original MOR
   numbering, passed to `interface_metrics` with `crop_start`).
4. Generate VHH library (h-NbBCII10, ~250 designs round 1, CDR3 9-18).
5. ESMFold monomer prefilter (discard low-pLDDT scaffolds).
6. AF2-multimer the survivors against the cropped extracellular target
   (binder = nanobody on chain A, target = epitope crop on chain B).
7. Interface metrics with `cdr_ranges` (from `library.json`) AND
   `hotspot_residues` + `crop_start` to compute `hotspot_satisfaction`.
8. Triage on `complex_confidence`; report applies the nanobody gate
   (complex pLDDT >85 ∧ ipsae ≥0.6 ∧ iptm ≥0.6 ∧ interface_plddt ≥87 ∧
   h3_plddt ≥86 ∧ cdr_contact_fraction ≥0.70 ∧ 600 ≤ BSA ≤ 1400 ∧
   clash ≤50).

Budget: **2 rounds**. Use round 1 to establish a high-quality cropped target
and confirm the gate is reachable; round 2 to refine library parameters if
gate unmet.

---

## Round 1 — initial library against ECL2 vestibule crop

### Target resolution

UniProt P35372, 400 aa. Class-A GPCR topology applied (confirmed by sequence
markers: GFGNFLVMYV near top of TM1, DRY at 164-166, conserved Cys141/Cys218
disulfide pairing). Topology:
- N-term: 1-64; TM1: 65-91; ICL1: 92-100; TM2: 101-125;
- ECL1: 126-141; TM3: 142-167 (DRY); ICL2: 168-181; TM4: 182-204;
- **ECL2: 205-227** (Cys218 disulfide to Cys141; vestibule lid);
- TM5: 228-258; ICL3: 259-269; TM6: 270-301; ECL3: 302-310; TM7: 311-336;
- C-term: 337-400.

### Crop: residues 138-235 (98 aa) — `crop_start=138`

Sequence:
```
TILCKIVISIDYYNMFTSIFTLCTMSVDRYIAVCHPVKALDFRTPRNAKIINVCNWILSSAIGLPVMFMATTKYRQGSIDCTLTFSHPTWYWENLLKI
```

Includes both Cys partners of the conserved class-A disulfide (C141 in TM3 top,
C218 in ECL2) so ECL2 hairpin folds correctly. Excludes the TM6/TM7 bundle and
intracellular tail where the prior run's designs glued onto the hydrophobic
non-physiological face. ~98 aa (vs 282 aa in the failed run) — comfortably
under the AF2 1024-aa cap.

### Hotspots (original MOR numbering): R212, T221, H224

Three solvent-exposed ECL2 lid residues lining the orthosteric vestibule
(morphinan/fentanyl pocket rim). Passed to `analysis.interface_metrics` as
`hotspot_residues="A212,A221,A224"` + `crop_start=138`.

### Round-1 parameters

- Library: 250 designs, h-NbBCII10, CDR3 9-18, seed=42
- ESMFold monomer prefilter threshold: pLDDT > 70 (standard foldable threshold;
  documented in `tools/nanobody_library.md`)
- AF2-multimer: num_recycle=3, num_models=1 (triage pass)
- Interface metrics on top candidates: cdr_ranges from library.json, hotspots
  + crop_start above

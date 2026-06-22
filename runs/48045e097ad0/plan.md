# Run plan — nanobody for μ-opioid receptor (OPRM1, MOR)

## Target resolution
- UniProt P35372 (Homo sapiens, MOR / OPRM1, 400 aa). Unambiguous.
- Structure: 6DDE chain R — active-state MOR cryo-EM bound to Gi + Nb33 (3.5 Å). Residues 65-345 present, no gaps.
- Target sequence for AF2: UniProt P35372[65-345] (281 aa). Uses canonical UniProt sequence (avoids 6DDE construct mutations / BRIL fusions) and matches the structural span. crop_start = 65.

## Epitope strategy
Class-A GPCR; design against the **extracellular face** only (the intracellular face engages Gi/arrestin). MOR extracellular loops (UniProt numbering):
- ECL1 ≈ 127-138
- ECL2 ≈ 210-227 (the dominant extracellular feature in class-A GPCRs; disulfide-anchored via C140-C217)
- ECL3 ≈ 304-315
- N-terminus 1-64 excluded (disordered, absent from cryo-EM).

Library screening lets AF2 itself find the side-on / extracellular docking pose; we do not pre-specify hotspots in this paradigm (cdr_contact_fraction / interface_plddt are the CDR-driven gate). interface_metrics is called without hotspot_residues.

## Library parameters
- Framework: h-NbBCII10 (only one wired). FR2 tetrad preserved by construction.
- n_designs: 60 (single-round budget; AF2-multimer on 281 + ~120 ≈ 400 aa is near the OOM line — each call is slow).
- CDR3 length: default 9–18 (CDR3 dominates the paratope).

## Pipeline
1. Library generation — 60 VHHs.
2. ESMFold monomer pre-filter, threshold 70 (lenient triage default).
3. AF2-multimer on top ~12 ESM survivors against MOR[65-345]; binder = nanobody.
4. interface_metrics per design with cdr_ranges from library.json (no hotspots — gate rests on cdr_contact_fraction).
5. Triage by complex_confidence; report applies the nanobody gate.

## Caveats
- 60 designs is well below the paper's 10⁴ — modest hit-rate expectation.
- Predicted KD is advisory only (not a gate).
- One round per the run budget directive.

## Round 1 — results

| rank | id      | esm   | complex_conf | ipsae  | iptm | pdockq2 |
|------|---------|-------|--------------|--------|------|---------|
| 1    | nb_0013 | 76.91 | 82.10        | 0.134  | 0.54 | 0.032   |
| 2    | nb_0022 | 76.08 | 80.35        | 0.014  | 0.46 | 0.019   |
| 3    | nb_0048 | 76.40 | 77.40        | 0.014  | 0.36 | 0.017   |
| 4    | nb_0031 | 75.75 | 75.28        | 0.000  | 0.15 | 0.009   |
| 5    | nb_0021 | 76.37 | 75.34        | 0.018  | 0.37 | 0.019   |
| 6    | nb_0012 | 76.01 | 75.59        | 0.000  | 0.13 | 0.009   |
| 7    | nb_0000 | 76.43 | 75.31        | 0.000  | 0.17 | 0.010   |
| 8    | nb_0006 | 76.18 | 73.74        | 0.000  | 0.14 | 0.009   |
| 9    | nb_0038 | 77.11 | 72.99        | 0.017  | 0.38 | 0.015   |
| 10   | nb_0008 | 76.98 | 71.99        | 0.000  | 0.25 | 0.011   |

Top design nb_0013 interface_metrics: BSA 2967 Å², cdr_contact_fraction 0.76,
interface_plddt 64.1, h3_plddt 50.3, clash_score 63 — high BSA + high clash +
low interface pLDDT = a non-physical "crammed" pose, not a true interface.

**Worked:** Pipeline ran end-to-end. 57/60 nanobodies passed ESM monomer
pre-filter (framework preservation works). 10 AF2-multimer jobs completed against
the full MOR[65-345] cryo-EM span without OOM (≈3.5 min each).

**Why none clear the gate:** A 60-design purely-combinatorial CDR library is
*three orders of magnitude* below the paper's 10⁴ regime — and even there, hit
rate after AF2 triage is single-digit percent. Best ipSAE = 0.134 vs gate ≥ 0.6;
best iptm = 0.54 vs gate ≥ 0.6; best complex_confidence = 82.1 vs gate > 85;
best interface_plddt = 64 vs gate ≥ 87. CDR-H3 pLDDT on the top design is
50 — AF2 isn't confident in the paratope geometry. The advisory PRODIGY KD of
0.04 nM on nb_0013 is meaningless given the failing structural confidence
metrics (PRODIGY is contact-counting; a high-BSA clashing pose looks "great").

**Gap:** Combinatorial diversity at n=60 doesn't sample the GPCR vestibule.
Class-A GPCRs present a narrow extracellular face (ECL1/2/3 + N-term, ≈80
residues of ≈281); a CDR-H3 has to land in that narrow window with the right
chemistry. With ~10² candidates we expect zero hits, and that's what we got.

**Next (out of budget for this run — recommendations only):**
1. Scale the library to ≥1k–10k VHHs (the paper's regime); the AF2 compute is
   the bottleneck, not the library generator.
2. Seed the library with a **natural llama VHH repertoire** via `external_fasta`
   instead of pure combinatorial diversification — natural CDR co-evolution
   beats random sampling per AF2 dollar.
3. Restrict the AF2 target sequence to the MOR extracellular vestibule
   (≈ residues 125-230 + 300-320 plus N-term) so AF2 can't dock the nanobody
   onto the TM bundle / intracellular face (some of the failures here probably
   docked outside the extracellular window).
4. Calibrate the gate on a known nanobody–GPCR co-crystal (e.g. Nb6/Nb39 vs
   KOR/MOR co-crystals) before trusting absolute pass/fail thresholds — the
   gate is provisional in the skill text.

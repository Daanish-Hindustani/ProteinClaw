# Run plan — TREM2 binder (PDB 5ELI), ≤250 aa

## Target resolution
- **Target:** human TREM2, UniProt **Q9NZC2** (230 aa), Ig-like V-set domain (annot. 29–112).
- **PDB:** 5ELI (apo TREM2 ectodomain, Kober et al. 2016 eLife). Chains A & B identical (crystallographic dimer).
- **Crop:** chain A, **20–131** (112 res), gap-free. Chain has gap 132–200 + isolated res 201 → avoided.
- Cropped PDB: `~/.proteinclaw/gpu-workspace/fffe79f7c846/pdb_fetch_0/5ELI_chainA_crop20-131.pdb`
- No co-crystal protein partner in 5ELI → hotspots from literature + structural sandbox.

## Round 1

### Scout hypotheses (§1.5)
1. **De novo precedent:** apical distal CDR-loop / hydrophobic face is the validated druggable surface; two anti-TREM2 scFv co-crystals (Szykowska 2021, PMID 34233201) hit the distal β-face; 60-80 aa helical binder. conf med-high.
2. **IgV designability:** β-strand interface conditioning gives ~9x hit-rate on *flat IgV β-faces* (PMC12852815); 65-120 aa. conf med-high. — **scoped to flat face only.**
3. **Ligand surface:** apical CDR loops (CDR1 39-47, CDR2 67-78, CDR3 115-120) = multi-ligand engagement face; hotspots **L69, W70** + basic anchors **R47, R62**; disease variants cluster here (R47H, R62H, T66M, Y38C). conf high. (PMID 32021611, 33090700, 41825226)
4. **Developability:** keep non-interface surface hydrophilic; bury core; 65-100 aa 3HB. conf med.

### Due diligence (§1.6)
- **Structural sandbox (biopython SASA + contacts on 5ELI):**
  - Exposed hydrophobic cluster on CDR2 loop: **L69 (0.48), L71 (0.71), L72 (0.35), F74 (0.52)**, W78 (0.40).
  - Basic anchors exposed: K42 (0.62), R47 (0.26), R62 (0.50), **R76 (0.54)**, R77, D87 (0.38).
  - **W70 is BURIED (relSASA<0.25)** — scouts named it a hotspot, but apo 5ELI shows L69 exposed, W70 not. → prefer L69.
  - **Crystallographic A–B contact lands on residues 67–79** (H67,N68,L69,L72,L75,R76,R77,W78) → this apical surface is a demonstrated protein-engageable interface, not a flat β-face.

### Debate (§1.7)
- **Contested:** topology — helical bundle (scout 1) vs β-strand pairing (scout 2).
- **Challenge → scout 2 (defend/revise):** target is the convex apical CDR-loop hydrophobic protrusion, NOT the flat GFCC′ face. Scout 2 **REVISED**: β-strand advantage was flat-face-specific; for a convex hydrophobic loop cluster a hotspot-driven helical/mixed RFD3 binder (60-90 aa) is correct (PMID 38798548 RFD binds loops; PMID 39763827 helical groove cradles convex protrusion). **Helical/mixed wins on evidence.**

### Converged design hypothesis (Round 1)
- **Epitope:** apical CDR2-loop hydrophobic cluster + flanking basic anchors.
- **Hotspots (5):** `A69,A71,A74,A62,A76` → L69, L71, F74 (hydrophobic burial core) + R62, R76 (basic anchors). All exposed, gap-free, chain A.
  - Hotspot atoms: L69 CG,CD1 · L71 CG,CD1 · F74 CG,CZ · R62 CZ,NH1 · R76 CZ,NH1.
- **Topology:** standard hotspot RFD3 (helical/mixed mini-binder).
- **Binder length:** broad round-1 sampling, range **65–90 aa** (≤250 ✓).
- **Funnel R1:** RFD3 num_designs=12 → MPNN 8 seq/backbone (=96) → ESM pLDDT≥70 → AF2-multimer on top survivors.
- **Quality gate:** ≥5 designs complex_confidence>75 (ideally ipsae≳0.3, BSA≳600, low clash, high hotspot satisfaction).

### Budget check
- Round 1: broad sampling (12 backbones). No hard round cap; stop when gate met.

## Round log

### R1 pipeline results
- **RFD3:** 12 backbones, all 71-aa binders (chain A), target chain B. (note: range 65-90 → all came out 71)
- **MPNN:** 8 seq/backbone = 96 sequences, temp 0.1, vanilla weights (Ala-rich — known caveat).
- **ESMFold (threshold pLDDT≥70):** mean 80.5 (batch1) / 79.5 (batch2). Nearly all pass.
  - Best-folding backbones: **b1 (82-84.6), b5 (80-84), b9 (80-83), b3 (80-82), b8 (~80, natural HTH seqs)**.
  - b7 gave very high ESM (85-87) but **poly-Ala low-complexity** sequences → suspicious (ESM loves regular helices); testing 1.
  - b4/b2 folded worst (~78-80, some Cys) → dropped from AF2 round.
- **Target seq (crop 20-131, 112aa, no gaps):** NTTVFQGVAGQSLQVSCPYDSMKHWGRRKAWCRQLGEKGPCQRVVSTHNLWLLSFLRRWNGSTAITDDTLGGTLTITLRNLQPHDAGLYQCQSLHGSEADTLRKVLVEVLAD
  - crop_start=20 for interface_metrics renumbering.

### AF2 shortlist (16, diverse across 11 backbones; binder→A, target→B, colabfold MSA, num_models=1)
1 b1s6(84.6) 2 b1s2(84.3) 3 b5s4(82.3) 4 b5s7(83.8) 5 b3s3(82.3) 6 b3s2(81.7)
7 b9s1(83.0) 8 b9s4(83.0) 9 b8s3(80.6) 10 b8s8(80.6) 11 b11s2(81.9) 12 b11s7(81.7)
13 b7s2(87.0,polyAla test) 14 b0s8(81.5) 15 b10s5(81.8) 16 b6s7(81.5)
(ran 14 of 16: skipped b7s2 poly-Ala after b5s7 confirmed poly-Ala collapses, and b8's 2nd seq)

### R1 AF2 ranked table (binder pLDDT / ipSAE / ipTM / pDockQ / BSA Å² / clash / hotspot-sat)
RANK by ipSAE (primary interface read). All msa_degraded=false.
| # | design | bb | binder-pLDDT | ipSAE | ipTM | pDockQ | BSA | clash | hsat |
|---|---|---|---|---|---|---|---|---|---|
| 1 | b9s4  | 9  | 96.8 | 0.70 | 0.83 | 0.25 | 1024 | 14.9 | 80% |
| 2 | b3s2  | 3  | 97.7 | 0.68 | 0.81 | 0.19 | 794  | 14.4 | 60% |
| 3 | b11s2 | 11 | 96.3 | 0.66 | 0.81 | 0.33 | 1650 | 16.0 | 80% |
| 4 | b1s2  | 1  | 97.1 | 0.65 | 0.81 | 0.17 | 870  | 11.3 | 60% |
| 5 | b10s5 | 10 | 94.7 | 0.59 | 0.77 | 0.31 | 1588 | 23.8 | 60% |
| 6 | b3s3  | 3  | 96.9 | 0.57 | 0.76 | 0.18 | 869  | 17.5 | 80% |
| 7 | b9s1  | 9  | 94.7 | 0.53 | 0.76 | 0.20 | 1088 | 20.3 | 80% |
- Borderline (ipSAE>0.3 but ipTM<0.7): b6s7(0.44/0.67), b6→b0s8(0.38/0.67), b11s7(0.37/0.59).
- Failures: b5(weak dock, ipSAE<0.1), b5s7 poly-Ala binder pLDDT COLLAPSED to 58 in complex, b8 HTH folds but ipSAE 0.01 (wrong dock), b1s6 cc91.9 but ipSAE 0.18 (folded, non-specific).

### Failure-pattern triage & epitope read
- **All 7 hits engage the L69/L71/F74 apical hydrophobic core** (satisfied in every one).
- **R62 consistently missed (~18-19 Å)** — it's a peripheral basic anchor on a separate strand; binders all converge on the hydrophobic cluster. R62 was over-ambitious; if a R2 were needed, drop R62 / re-task to {L69,L71,F74,R76,W78}.
- ESM "high-but-collapses": poly-Ala b5s7/b7 — see self-evolution note.

### OUTCOME: QUALITY GATE MET (round 1, no round 2 needed)
- 7 designs cross the full Bennett/BindCraft strong-hit gate (binder pLDDT>80, ipSAE≳0.3, ipTM≥0.7) across 5 distinct backbones (1,3,9,10,11).
- Gate (≥5 cc>75) far exceeded. Finalize and stop. Hypothesis (apical CDR2 hydrophobic-cluster epitope + hotspot helical/mixed RFD3 mini-binder) validated.

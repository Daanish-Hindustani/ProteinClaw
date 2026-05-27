# proteinclaw run notebook — PD-L1 IgV binder (60–80 aa)

Prompt: "design a 60-80 residue binder to PD-L1's IgV domain"
Run dir: runs/f1c91f97b666 — Budget: 12 rounds.

## Target resolution (fixed)
- Target: **PD-L1 / CD274**, UniProt **Q9NZQ7**, Homo sapiens, 290 aa.
- IgV (Ig-like V-type) domain: residues **19–127** (UniProt annotation).
- Structure: **4ZQK** (human PD-1/PD-L1 complex, X-ray 2.45 Å).
  - chain A = PD-L1 (present 18–132 gap-free over the IgV; gaps only at 133+ in C-domain).
  - chain B = PD-1 (natural ligand → used to read the epitope).
- RFD3 target crop: **chain A, 18–132** → `pdb_fetch_1/4ZQK_chainA_crop18-132.pdb` (115 res, gap-free, ≤130).

## §1.6 Due diligence
### Structural sandbox (scratch/epitope.py — biopython, 4.5 Å heavy-atom contacts A↔B)
PD-1 epitope on PD-L1 IgV, ranked: Y123(55) > K124(27) > Q66(23) > D122(19) > Y56(18) >
R113(17) > R125(16) > A121(15) > M115(9) > F19/D26(7) > I54(4). Front CC'FG β-sheet.
Rel SASA (isolated PD-L1): Y123 48%, A121 57%, M115 22%, R113 38%, Q66 26%, Y56 20% (all exposed);
E58 8% (buried → skip).

### Literature corroboration (research tools — not LLM-filtered, work fine)
- Canonical "five hotspot residues" PD-L1 CC'FG sheet = Y56, E58, R113, M115, Y123 (PMID 34093837/PMC8176414; PMID 30917623/PMC6470598).
- Virtual ala-scan hotspots: Y56, Q66, M115, D122, Y123, R125 (PMID 29203283).
- GFCC' front strands form interface; D122/Y123/K124/R125 buried at interface (PMC7272049).
- **My contact map independently reproduced the literature epitope** → high confidence.

## Scouts (§1.5)
- **PD-L1-precedent scout: REFUSED on BOTH `research` (Sonnet) and `research_pro` (Opus)** by API
  Usage-Policy filter (documented checkpoint-topic failure). Dropped per skill; covered by own DD above.
- **Ig-fold designability scout (med-high):** flat Ig-like V β-sheet faces are HARD; standard
  hotspot-directed RFdiffusion mostly yields α-helical bundles, <5% β-strand pairing on flat faces.
  BindCraft hit 70% on a flat Ig V-type face with **3 dispersed hotspots**, 80–120 aa. 3–6 hotspots
  standard (PMC12852815, PMC12724655, PMID 37433327, 37889566). Open Q: PD-L1 CC'FG may want 5–6.
- **Developability scout (med):** surface hydrophobicity (SAP) is the dominant liability for small
  helical binders; mitigate with ProteinMPNN **soluble weights** + low exposed-apolar fraction,
  net charge ~−7 (PMC9850923, PMC10990136, PMID 41284265).

## §1.7 Debate → ROUND 1 hypothesis
1. **Length**: user spec 60–80 (HARD constraint) vs scout 80–120. → Honor user, **bias to top: 70–80**.
   Decisive: user requirement non-negotiable; scout's "scaffold-volume helps β-sheet packing" justifies
   biasing up within the allowed window.
2. **Hotspot count**: scout flat-face evidence (3 dispersed, 70%) favors fewer for designability; my
   structural+lit evidence supports the 5-residue canonical set. → **Compromise: 4 dispersed hotspots
   = Y56, R113, M115, Y123.** Drop E58 (buried) and A121 (redundant, adjacent to Y123, weak CB anchor).
   Keep the 3 aromatic/hydrophobic anchors (Y56,M115,Y123) for packing + R113 for centering/specificity.
3. **Topology**: scout favors β-strand binders, but **our RFD3 wrapper has no strand-conditioning lever**
   → accept RFD3 helical/mixed bias for R1; `is_non_loopy=true` (canon). If R1 docks poorly → R2 partial diffusion.
4. **Developability**: soluble MPNN weights recommended but **NOT exposed in wrapper (vanilla only)** →
   flag limitation; report interface metrics; cannot change weights this run.

### Round-1 design hypothesis
- Epitope: block PD-1 face (CC'FG front β-sheet).
- Hotspots (4): **Y56, R113, M115, Y123** (chain A). Atoms: Y56 CG,OH · R113 CZ,NH1 · M115 CG,SD · Y123 CG,OH.
- RFD3: `binder_length="70-80"`, `num_designs=12` (hard band 8–12), canon params, is_non_loopy=true.
- MPNN: `num_sequences=4`, `sampling_temp=0.1` (vanilla weights) → 48 seqs.
- ESM: batch 48, keep pLDDT ≥ 70.
- AF2-multimer: top survivors by ESM pLDDT (cap ~24), colabfold MSA, num_models=1. complex pLDDT = ranking.
- Expectation: flat β-face is hard → modest R1 hit-rate likely; aromatic anchors counter flatness.

### Round 1 execution log
- RFD3: 12 backbones, binder=chainA 77 aa each, target=chainB. 138 s. (num_timesteps default 200 — note:
  tool-skill said 50 but live schema default is 200; used live default, more converged.)
- MPNN: 48 seqs (4×12), vanilla weights, temp 0.1. Topology mix: helical (b0,1,2,6,8,9), β/mixed (b3,4,7,11),
  α/β (b5,10). b4 cleanest β (MPNN score 0.67, 82% recovery).
- ESM: ALL 48 ≥ 70 (mean 79.7, range 70.6–82.9). Monomer pre-filter non-discriminating here → AF2 decides.
- Target seq (frozen, res 18–132): AFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQRARLLKDQLSLGNAALQITDVKLQDAGVYRCMISYGGADYKRITVKVNA
- AF2 selection (16, biased to β-topology to TEST the fold-scout hypothesis on flat Ig face):
  β: idx16(b4),19(b4),12(b3),13(b3),29(b7),28(b7),44(b11),45(b11);
  helical: idx3(b0),8(b2),10(b2),32(b8),38(b9),26(b6),7(b1),22(b5).
  Down-weighted Ala-rich idx33(8b poly-A),25(6b),46(11c) per learned note.

### Round 1 RESULTS — GATE MET (stop)
AF2 (16 jobs, all msa_degraded=false). 4 designs clear the STRICT 5-metric AND gate:

| design | bb | topology | complex pLDDT | ipSAE | ipTM | BSA Å² | hotspot sat | clash/1k |
|---|---|---|---|---|---|---|---|---|
| idx8  | b2 | α-bundle | 96.8 | 0.796 | 0.89 | 1585.6 | 1.00 | 12.2 |
| idx7  | b1 | α-bundle | 96.6 | 0.767 | 0.87 | 1404.3 | 1.00 | 16.9 |
| idx32 | b8 | α-bundle | 95.4 | 0.664 | 0.82 | 1409.8 | 1.00 | 6.2  |
| idx38 | b9 | α-bundle | 93.7 | 0.610 | 0.79 | 1369.0 | 1.00 | 17.8 |

- **4/16 AF2 jobs are full-gate hits** (4/48 designs). ALL 4 engage the intended PD-1 epitope
  (Y56,R113,M115,Y123) at 100% hotspot satisfaction → binders block the PD-1 face as designed.
- Marginal (ipSAE 0.26–0.28, fail gate): idx10(b2), idx12(b3), idx26(b6).
- **KEY FINDING (failure-pattern triage):** every generic β-topology design (b3,4,7,11 = 8 seqs)
  FAILED to dock (ipSAE ≤ 0.28, mostly ~0.01) despite folding well in ESM — the "folds OK / docks
  wrong" quadrant. All 4 hits are α-helical bundles. This *refines* the fold-scout hypothesis: its
  β-advantage was for β-STRAND-CONDITIONED RFdiffusion (explicit edge-strand pairing), which our
  wrapper cannot do. Unconditioned RFD3 β-sandwiches present no interface strand → don't dock.
- Hits span 4 independent backbones → robust, not one lucky scaffold. num_models=1 (high ESM + high
  AF2 = trustworthy quadrant; no confirmation pass needed). Recommend num_models=5 confirmation +
  OpenMM relax (to drop the moderate clash on idx7/38) as a downstream hardening step.

### Budget check: Round 1 of 12 — GATE MET (≥3 hits), finalizing. No further rounds.

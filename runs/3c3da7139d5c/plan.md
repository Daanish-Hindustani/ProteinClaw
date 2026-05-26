# ProteinClaw run notebook — binder to ubiquitin (1UBQ)

Budget: **1 round** (single hypothesis cycle, one RFD3 call). Gate: ≥5 designs complex_confidence > 75.

## Round 1

### Target resolution
- **PDB 1UBQ** chain A — human ubiquitin, 1.8 Å X-ray (Vijay-Kumar 1987), the
  reference ubiquitin structure. Chain A = 76 protein residues (1-76) + 58 waters
  (numbered 77-134). Crop **1-76** = the complete β-grasp domain, **gap-free**.
  Crop path: `/home/ubuntu/.proteinclaw/gpu-workspace/3c3da7139d5c/pdb_fetch_0/1UBQ_chainA_crop1-76.pdb`
- **UniProt P0CG48** (Polyubiquitin-C, 685 aa = 9× ubiquitin). Monomer = res 1-76:
  `MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG`

### Scout hypotheses
- **Scout 1 (Ile44 patch, HIGH):** canonical recognition quartet = Leu8/Ile44/Val70/His68,
  the surface used by >150 UBD–Ub complexes (UIM/UBA/UBZ/proteasome). Cites PMID 24151880,
  21113239, 15837191, 36532480, 39600913, 39062736. Ile36 patch + Phe4/TEK are separable
  alt surfaces. Open Q: His68 may be peripheral (triad vs quartet).
- **Scout 2 (binder class, MED-HIGH):** UbV (76-aa β-grasp, phage-evolved) is best-validated
  precedent, nM–sub-nM (PMID 37918563, 30713027). BUT that's library selection of UbV-as-ligand
  to enzyme grooves — not de novo diffusion against free Ub. Notes NO published de novo binder
  to *free* ubiquitin (a genuine novelty/risk). Ile44 patch confirmed as the epitope.
- **Scout 3 (length/topology, MED):** flat ~400 Å² hydrophobic patch → **helical bundle, 50-65 aa**
  best (Cao 2022 PMID 35332283; PDGFRα flat-surface helical preference PMC12852815). Caveats:
  flat patch is edge-of-distribution; small target (76 aa) risks steric wrap if binder too large.

### Due diligence (structural sandbox, biopython SASA)
relSASA on 1UBQ 1-76: Leu8=0.69, His68=0.40 (well exposed); Ile44=0.15, Val70=0.22
(central, partly recessed → confirms a FLAT patch, not a pocket). Gly47=0.75, Ala46=0.58 rim.
C-terminal tail Arg72-Gly76 highly exposed/flexible (Gly76 rel=1.34) — correctly EXCLUDED
(conjugation tail, not a docking site). Ile36 (0.15) buried — alt patch less accessible. SASA
corroborates Scout 1's quartet as the docking face.

### Debate / adjudication
- Contested: topology/length (Scout 2 β-grasp 76 aa vs Scout 3 helical 50-65 aa). **Resolved on
  modality**: pipeline is de novo RFD3, so Scout 3's helical-mini-binder evidence is decisive;
  Scout 2's UbV evidence corroborates the epitope but applies to a different (library) modality.
  Decisive evidence: Cao 2022 + PDGFRα flat-surface helical preference. No re-spawn needed.
- His68 triad-vs-quartet (Scout 1 open Q): SASA shows His68 exposed (0.40) → keep in quartet;
  costs nothing and may aid selectivity.

### CHOSEN DESIGN HYPOTHESIS
- Hotspots: **A8, A44, A68, A70** (Ile44 hydrophobic patch). Side-chain-representative atoms:
  A8 (Leu) CG,CD1; A44 (Ile) CG1,CD1; A68 (His) CG,ND1; A70 (Val) CG1,CG2.
- Binder length: **55-70** (helical sweet spot, sized to a flat patch on a 76-aa target).
- num_designs: **16** (rounds=1, hard target, bias to upper band of difficulty).
- MPNN: 2 seq/backbone, temp 0.1. ESM cut 70. AF2 colabfold MSA, num_models=1.
- Honest risk: no de novo precedent vs free ubiquitin; flat small patch is hard — hit-rate may be low.

### Pipeline execution log
- Target resolution + research + sandbox + deliberation: COMPLETE (above).
- **RFD3 backbone generation: FAILED — infrastructure, not design.**
  - 3 invocations of `design.rfdiffusion3`, all returned `Stream closed` *immediately*:
    (1) hotspots A8/A44/A68/A70 + hotspot_atoms dict, len 55-70, n=16;
    (2) identical retry; (3) same but hotspot_atoms dropped (wrapper CA,CB default).
  - Diagnostics: GPU idle (0 MiB used) throughout; NO docker container ever launched
    (`docker ps -a` empty); NO `rfdiffusion3_*` workspace dir created; `trace.jsonl`
    stops at the plan.md write — **no RFD3 tool_use was ever recorded**.
  - Image IS built (`proteinclaw/rfdiffusion3:0.1.0` present). GPU = 23 GB (above 22 GB floor).
  - Conclusion: the in-process MCP server crashes on `design.rfdiffusion3` dispatch,
    severing the SDK stream before docker run. Same failure regardless of params → not a
    parameter/crop/hotspot issue. Needs engineering attention (MCP dispatch / RFD3 wrapper
    pre-launch path), not a design retry.
  - Also noted: only `proteinmpnn` + `rfdiffusion3` images exist locally; `esmfold` and
    `alphafold2_multimer` images are NOT built — downstream stages would also be blocked.
- **No backbones produced → MPNN/ESM/AF2 not run → no ranked designs this round.**
  Budget (1 round) exhausted on the blocked stage. Status: BLOCKED, needs human/infra fix.

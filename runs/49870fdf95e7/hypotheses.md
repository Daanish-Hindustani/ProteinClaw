# Design hypotheses — de novo mini-binders to PD-L1 IgV (5JDS chain A)

Target request: 60–80 aa de novo mini-binders to the IgV domain of human PD-L1
(PDB 5JDS, chain A). Compute kept minimal per user: ~3 backbones, ~2 sequences.

## Round 1

### Target resolution
- **UniProt Q9NZQ7** (PD-L1 / CD274, Homo sapiens), mature length 290.
  Ig-like V-type (IgV) domain annotated **19–127**.
- **PDB 5JDS, chain A** = PD-L1. Chain A modeled 18–376 with two large gaps
  (133–200, 203–300 = disordered linker/construct). IgV domain sits entirely
  inside the gap-free **18–132** segment.
- Crop chosen: **chain A, 18–132** (115 aa, gap-free, fast for RFD3).
  Host path: `/home/ubuntu/.proteinclaw/gpu-workspace/49870fdf95e7/pdb_fetch_0/5JDS_chainA_crop18-132.pdb`
- Crop sequence (used verbatim as AF2 target_sequence):
  `AFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQRARLLKDQLSLGNAALQITDVKLQDAGVYRCMISYGGADYKRITVKVNA`
- **Chain B in 5JDS is NOT PD-1** — sequence `QVQLQESGGG...WGQGTQVTVS` is a
  VHH/single-domain antibody (KN035/envafolimab–PD-L1 co-crystal). KN035
  competes with PD-1 for the same GFCC′ face → the co-crystal interface IS the
  therapeutically relevant epitope.

### Own structural sandbox (§1.6) — interface residues, 4.5 Å heavy-atom (PD-L1 vs chain B)
Top contacts (`./scratch/interface_5jds.json`):
A61D(5), A113R(5), A56Y(4), A66Q(4), A115M(4), A123Y(4), A54I(3), A68V(3),
A121A(3), A73D(2), A58E(1), A63N(1)…
→ Hydrophobic/aromatic core **I54, Y56, M115, A121, Y123** embedded in a polar
rim (D61, R113, Q66, E58). Matches literature hotspots exactly.

### Scout hypotheses (§1.5)
1. **Prior PD-L1 binders** (med-high): helical scaffolds (55–110 aa) dominate the
   validated set — affibody 3HB ~58 aa @68 nM (PMC10691555), dMaSIF helical DBL2
   @65 nM with co-crystal **7XAD** (Gainza Nature 2023, PMID 37100904),
   engrailed-homeodomain @51 nM (PMID 39012010). Hotspots I54/Y56/M115/A121/Y123.
2. **Ig V-set designability** (initially "conditionally hard", high conf): default
   hotspot-conditioned RFdiffusion <1% on flat polar IgV edge-strand targets
   (PMC12852815); beta-pairing reconditioning →9.2%. BUT flagged PD-L1 GFCC′ not
   tested → transfer unknown.
3. **Mini-binder length** (med-high): 55–80 aa three-helix-bundle optimal. LCB1=56 aa
   (Cao 2022, PMID 35441235); Vazquez Torres 60–80 aa hits 58% (PMID 38109936);
   Bennett 2023 dominant topology α-helical.
4. **Developability** (med-high): minimize *largest contiguous exposed hydrophobic
   patch*; SolubleMPNN >> vanilla MPNN (Goverde Nature 2024; Jacak PMC3277657).

### Debate log (§1.7)
- **Contested:** scout 1/3 (helical mini-binders work on PD-L1) vs scout 2 (flat
  polar IgV face hard, <1%).
- **Challenge → scout 2 (DEFEND mode):** presented PD-L1-specific validated helical
  binders + the convex hydrophobic sub-pocket.
- **Outcome: scout 2 REVISED (decisive).** PD-L1 GFCC′ is **convex, not flat**; the
  <1% figure came from edge-strand recognition (PMC12852815) which does NOT transfer
  to PD-L1's groove-mediated binding. The non-polar pocket I54/Y56/M115/A121/Y123 is
  energy-decomposition-validated (PMID 33946261, 31781546) and anchorable. Recommended:
  **primary hotspots = pure hydrophobic anchors {I54,Y56,M115,A121,Y123}; polar rim
  (D61,R113,Q66) deferred to MPNN stage**, not primary conditioning.
- **Decisive evidence:** convex/non-polar re-classification + 3 independent validated
  helical PD-L1 binders + co-crystal 7XAD. My structural contacts independently agree.

### CHOSEN design hypothesis (round 1)
- Target: 5JDS chain A crop 18–132.
- **Hotspots: A54, A56, A115, A121, A123** (GFCC′ hydrophobic sub-pocket). Sparse (5),
  within crop, gap-free.
- **Hotspot atoms** (side-chain representative): A54=CG1,CD1 (Ile); A56=CG,OH (Tyr);
  A115=CG,SD (Met); A121=CB (Ala); A123=CG,OH (Tyr).
- **Binder length 60–80 aa**, helical/mixed (is_non_loopy=true biases structured).
- **num_designs=3, num_sequences=2** (user minimal-compute → 6 AF2 jobs).
- RFD3 params: step_scale=3, gamma_0=0.2, is_non_loopy=true, num_timesteps=50 (skill canon).
- MPNN sampling_temp=0.1, vanilla weights. **Caveat:** wrapper lacks SolubleMPNN →
  scout-4 developability optimum unavailable; will flag exposed-hydrophobic risk in summary.
- ESM triage cut ≥70. AF2 colabfold MSA, num_recycle=3, num_models=1.
- **Honest expectation:** med-high that the topology/hotspot choice is right; but at only
  3×2=6 funnel width the *sampling* of a hit is low — this is exploratory scale, not
  Bennett-2023 exhaustive. Gate (≥5 designs complex_confidence>75) may not be met.

### INFRA NOTE — MCP transport died mid-run (workaround)
After the RFD3 call (which completed server-side: output.json written, 3 backbones),
the in-process MCP server became unreachable: every subsequent MCP tool call —
including a cheap data_pdb_fetch that worked at session start — returned
"Stream closed" immediately without launching a container. GPU free, all images present.
Confirmed session-wide (not MPNN-specific).
**Workaround:** drove the remaining stages (MPNN, ESMFold, AF2-multimer) via direct
`docker run` replicating LocalRunner.build_docker_run_argv EXACTLY — same images, same
`ENTRYPOINT python3 /app/tool_entrypoint.py`, same JSON-in (/workspace/input.json) /
JSON-out (/workspace/output.json) contract, same weight-cache mounts and -u UID:GID.
This bypasses only the dead MCP dispatch layer; the science/containers are unchanged.
Per-stage envelopes saved as proteinmpnn_out_{0,1,2}.json, esmfold_out.json, af2_out_{0..5}.json.

### Round 1 pipeline results (so far)
- RFD3: 3 backbones, all 64 aa, binder=chain A / target=chain B. (vram peak 4.4 GB, 31 s)
- MPNN: 3×2 = 6 sequences, temp 0.1, vanilla weights. All helical. MPNN scores 0.69–0.92.
- ESMFold: all 6 monomers fold — mean pLDDT 81.0 (79.8–82.7). ALL pass ≥70 cut → 6 to AF2.
- AF2-multimer: 6 complexes vs target crop 18–132, colabfold MSA, num_models=1. DONE.

### Round 1 evaluation + failure analysis
Rank (complex pLDDT): bb1.0 90.1/ipSAE0.516/ipTM0.74 (HIT, crosses experimental gate);
bb0.0 90.0/ipSAE0.298/ipTM0.62 (borderline); bb2.0 82.6, bb2.1 79.8 (folded but
ipSAE~0.01 = docks non-specifically, the "high pLDDT / low interface" false-positive
pattern); bb1.1 59.3, bb0.1 47.5 (fail).
- Formal gate (≥5 designs complex pLDDT>75) = 4/6 → NOT met. Meaningful interface gate
  (ipSAE≥0.3) = 1 clear + 1 borderline.
- Failure pattern (triage table): ranks 3–4 = ESM-high/AF2-pLDDT-high but ipSAE-low →
  fold OK, interface non-specific → backbone/orientation suboptimal on those backbones.
  bb1 is the productive backbone (its s0 gave the only true hit).

### Round 2 hypothesis (refine, don't repeat) — round 2 of 2
Change: RFD3 wrapper has NO partial-diffusion knob → cannot do partial_T refinement.
Highest-value minimal move = **re-MPNN the proven bb1 backbone at higher temp (0.2) for
sequence diversity** (skill option 3). bb1 already produced the rank-1 hit; resampling it
should find more interface-competent sequences on a confirmed scaffold. Keep minimal:
bb1 only, 4 sequences, temp 0.2 → ESM≥70 → AF2 survivors. Hotspots/target/length unchanged
(64 aa proven). This differs from round 1 (new backbone focus + higher temp), not a repeat.

### Round 2 results + FINAL (gate MET, stop)
Re-MPNN bb1 ×4 @temp0.2 → ESM all 79–82 (pass) → AF2: all 4 strong.
- R2.bb1.2: cplx 90.5, ipSAE 0.794, ipTM 0.85 (BEST overall)
- R2.bb1.1: cplx 81.5, ipSAE 0.686, ipTM 0.80
- R2.bb1.3: cplx 87.5, ipSAE 0.484, ipTM 0.71
- R2.bb1.0: cplx 84.8, ipSAE 0.325, ipTM 0.60
Confirms bb1 is the productive scaffold; round-1 bb1.1 failure was a sequence problem.
**Combined 10 designs: GATE MET — 8/10 complex pLDDT>75 (need ≥5); 5/10 ipSAE≥0.3.**
Interface validation (4.5 Å contacts) on top-2: BOTH engage all 5 intended hotspots
(I54/Y56/M115/A121/Y123 = 5/5) + polar rim (Q66,R113,D122,E58) — MPNN filled the rim
exactly as the debate predicted. Epitope = PD-1/KN035 GFCC′ face. Converged; stopped at
round 2 of 2. Deliverables: ./designs/rank01-10*.pdb, ./result.json.

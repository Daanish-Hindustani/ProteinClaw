# Design hypotheses — de novo mini-binders to PD-L1 IgV (5JDS chain A)

## Target resolution
- PD-L1 = UniProt **Q9NZQ7** (290 aa). IgV (Ig-like V-type) domain = UniProt 19–127.
- PDB **5JDS** = co-crystal of **KN035 single-domain antibody (chain B) : human PD-L1 (chain A)**.
- Chain A present 18–376 with gaps 133–200 and 203–300. IgV crop **18–132** is gap-free, 115 aa, ≤130 → fast RFD3.
- Cropped target path: `/home/ubuntu/.proteinclaw/gpu-workspace/2beba0d8c032/pdb_fetch_0/5JDS_chainA_crop18-132.pdb`
- This crop is the AF2 `target_sequence` in step 7.

---

## Round 1

### Scout hypotheses (parallel fan-out, §1.5)
- **Known-interfaces scout** (research, Sonnet): REFUSED (Usage-Policy, immune-checkpoint topic). Re-spawned on research_pro (Opus): ALSO REFUSED. Covered by own DD below.
- **Hotspot-residues scout** (Sonnet): REFUSED. research_pro (Opus): ALSO REFUSED. Covered by own DD below.
- **Length/topology scout**: returned truncated interim note (no final hypothesis); content subsumed by prior-campaigns scout + challenge scout.
- **Prior-campaigns scout** (delivered full hypothesis, HIGH conf):
  - Front β-sheet (GFCC′) PD-1-competitive face is the canonical epitope.
  - KN035 co-crystal (5JDS) alanine scan: Ile54/Tyr56/Glu58/Gln66/Arg113 give 80–400× affinity drops → dominant hotspot cluster. (PMID 28280600 / PMC5341541)
  - Cao 2022 Rosetta miniproteins on PD-L1: 65–374 nM, polar-rim interactions suboptimal (PMC9621694).
  - RFdiffusion 2023 included PD-L1 among 5 targets, ~19% success, ~100× over Rosetta (PMID 37433327).
  - 5HCS five-helix concave scaffold on PD-1 site: 646 pM, needed ~33 Å span — "almost impossible with smaller miniproteins" (PMID 38746206/PMC11092582).
  - PD-L1 IgV front face classified CONVEX → favors helical-concave/extended, disfavors sub-60 aa globular (PMC11865580).

### Own due diligence (§1.6) — REQUIRED, both checks done
1. **Structural sandbox** (`scratch/cocrystal_epitope.py` on 5JDS, chain A vs chain B KN035, 5.0 Å heavy-atom):
   20 epitope residues, all in crop 18–132, none in gaps. Ranked by #contacts:
   **D61(12), R113(6), Y123(6), Q66(5), Y56(5), A121(5), M115(4), D122(3), I54(3), E58(2), R125(1)** + N63,K62,V68,D73,G119/120,E60,H69,S117.
   → Independently confirms the front-face cluster; D61 is the single biggest contact hub.
2. **Own literature search** (research.literature_search): KN035 binds PD-L1 via a single 21-aa CDR loop engaging **Ile54, Tyr56, Arg113** (PMC7057419/PMID 32051289); PD-1 interface "largely coincident with that of KN035," same hotspots (PMID 28280600); per-residue mutagenesis done (PMID 29163822/PMC5685743).

### Debate log (§1.7)
- **Contested claim:** prior-campaigns scout said sub-60-aa / small globular miniproteins underperform on PD-L1's convex face; user fixed 60–80 aa.
- **Challenge → DEFEND/REVISE (research scout):** verdict **REVISE** (med conf):
  - 60–80 aa IS workable; the disfavored threshold is ~<65 aa globular, not 80 aa.
  - Pure helical bundle = worst choice on convex IgV face; mixed α/β with an edge-strand (β-pairing RFdiffusion) is best (9.2% vs 0.98% filter pass; PMID 41519838/PMC12852815). BindCraft PD-L1 binder 615 nM, AF2-multimer in loop (Nature 2025).
  - **Bias toward 75–80 aa** to allow 2–3 buttressing helices around a short interfacial strand.
- **Adjudication:** Decisive evidence (5HCS + β-pairing papers) → bias binder length to **upper end of allowed window (70–80)**. Our RFD3 wrapper is vanilla (no β-pairing conditioning) with `is_non_loopy=true`, so we cannot force edge-strand topology — accept this is exploratory and may favor helical solutions. Epitope choice (front PD-1-competitive face) is UNCONTESTED across scout + own structural + own literature → high confidence.

### CHOSEN DESIGN HYPOTHESIS (drives §§3–8)
- **Chain/crop:** 5JDS chain A, crop 18–132 (= AF2 target_sequence).
- **Hotspots (5, well-distributed across the front GFCC′ face, lit+structure validated):**
  **A56 (Y), A61 (D), A113 (R), A115 (M), A123 (Y)**
  - Y56 + R113: KN035 & PD-1 alanine-scan hotspots, aromatic + charged anchors.
  - D61: top structural contact hub (12 contacts).
  - M115: hydrophobic anchor; Y123: aromatic, 6 contacts. N- and C-cluster both represented.
  - hotspot_atoms: wrapper default (CA,CB) — robust for an exploratory run.
- **Binder length:** 70–80 aa (upper end per debate).
- **Compute (user-mandated minimal):** num_designs=3, num_sequences=2 → 6 AF2 jobs.
- **RFD3 params:** num_timesteps=50, step_scale=3, gamma_0=0.2, is_non_loopy=true (PPI canon).
- **MPNN:** sampling_temp=0.1 (round-1 high-confidence default).
- **ESM triage cut:** mean pLDDT ≥ 70.
- **AF2:** colabfold MSA, num_recycle=3, num_models=1.
- **Honesty note:** 3×2 funnel is pipeline-validation / exploratory scale, ~3 orders of magnitude below Bennett-2023 gold standard (~10k backbones). Quality gate (≥5 designs >75 pLDDT) is unlikely to be met at this funnel width; this is by user design (minimal compute), not a targeting failure.

### ROUND 1 EXECUTION — BLOCKED (infrastructure)
- RFD3 dispatch (`design_rfdiffusion3`, the params above) returned **`Stream closed`** twice. GPU stayed idle (0 MiB used), no container ever launched (`docker ps -a` empty) → failed at MCP dispatch, before `docker run`.
- Health-checked the MCP layer with a fast `data_pdb_fetch` (which succeeded earlier): also `Stream closed`, twice. → the **in-process MCP server became unresponsive** for this session; the crash coincided with the first RFD3 dispatch.
- Host state: all 5 docker images present (incl. `proteinclaw/rfdiffusion3:0.1.0`), docker daemon healthy (29.1.3), SDK parent PID 186688 alive, GPU free (22.5 GB). No OOM in dmesg.
- A **concurrent run** (`/tmp/live_run5.log`, session `49870fdf95e7`) is active on the same host/GPU/MCP infra — possible shared-resource / shared-MCP contention. Cannot restart the MCP server from inside the agent.
- **Outcome:** planning/deliberation COMPLETE (this file). Compute pipeline (RFD3→MPNN→ESM→AF2) NOT run — blocked by MCP transport, not by design choices. The design hypothesis above is ready to execute verbatim once the MCP server is healthy.

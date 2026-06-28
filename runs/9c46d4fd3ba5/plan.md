# ProteinClaw run 9c46d4fd3ba5

## Target
- Ubiquitin PDB 1UBQ chain A.
- Protein crop: residues 1-76. Chain-specific raw fetch included HOH records as residues 77-134, so crop 1-76 is the true ubiquitin protein chain.
- Sequence: MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG
- No gaps in 1-76 crop.

## Round 1 research
- Native subagent literature hypothesis: target canonical Ile44 ubiquitin-binding patch: L8, I44, H68, V70, with Gly47 backbone as orientation context. Cited UBA/UIM/CUE convergence, PDB 1WR1, PMID 15837191, PMID 12970172, reviews PMID 19773779 and PMID 22482907.
- ProteinClaw PubMed search retrieved UIM-ubiquitin complex and related ubiquitin-binding domain literature.
- Structural evidence: ProteinClaw PDB analysis confirms A8, A44, A68, A70 are present in 1UBQ crop.

## Round 1 debate
- Contested point: Ile44 patch vs alternate polar/acidic patch or C-terminal tail.
- Decision: Ile44 patch wins. It is the canonical recognition surface and gives RFdiffusion3 sparse hotspot anchors on a compact target. Tail/C-terminal region is flexible and less suitable as primary epitope.
- Risk: the Ile44 patch is shallow and native UBDs are often weak; require AF2-multimer/ipSAE/interface QC rather than trusting monomer fold.

## Round 1 design hypothesis
- Target PDB: /home/ubuntu/.proteinclaw/gpu-workspace/9c46d4fd3ba5/pdb_fetch_3/1UBQ_chainA_crop1-76.pdb
- Hotspots: A8,A44,A68,A70
- Hotspot atom hints: L8 CD1/CD2, I44 CD1/CG1/CG2, H68 ND1/NE2/CE1, V70 CG1/CG2
- Binder length: 65 aa compact minibinder.
- Funnel: RFdiffusion3 8 backbones -> ProteinMPNN 4 sequences/backbone (soluble, T=0.1) -> ESMFold monomer filter pLDDT >=70 -> AF2-multimer on best-per-backbone or top survivors -> interface metrics on top complexes.


## Native Debate Record

{
  "type": "debate_record",
  "subagent_type": "native_subagent",
  "prompt": "Critique subagent result for round-1 Ile44-patch ubiquitin minibinder design.",
  "position": "",
  "summary": "Critique accepted as a risk modifier, not as a reason to switch. The critic agrees the Ile44 patch is biologically plausible and present, but warns that sparse hydrophobic hotspots can be underconstrained on small ubiquitin. Decision: continue current run because RFD3 has already generated backbones using A8/A44/A68/A70 and H68 provides some directional context; evaluate stringently with AF2 ipSAE, hotspot satisfaction, BSA, clash, and whether the interface looks over-buried or generic. If round 1 fails by ipSAE/hotspot specificity, next round should test either polar-neighbor expansion around Q40/R42/H68/R72 or an alternate polar patch.",
  "evidence": [
    "Critique subagent: Ile44 patch is canonical but shallow; hydrophobic-only docking may look falsely good.",
    "PDB analysis confirms true ubiquitin crop is residues 1-76; avoids HOH residues 77-134.",
    "Current hotspot set includes H68 alongside L8/I44/V70, adding partial polar/directional context."
  ],
  "decision": "Continue the current Ile44-patch funnel. Do not report hits unless strict multi-metric gate passes; recommend polar-neighbor refinement if this round produces plausible but under-specific binders.",
  "ts": 1782616440.291427
}

## Round 1 results
- RFD3: 8 backbones generated against ubiquitin crop 1-76. Output convention: binder chain A, target chain B.
- ProteinMPNN: 32 sequences generated (4/backbone), soluble weights, T=0.1.
- ESMFold: 32 monomer structures, mean pLDDT 77.4, range 58.5-81.2; 30/32 passed pLDDT >=70.
- AF2-multimer triage: 8 best-per-backbone representatives. No MSA-degraded designs.
- Confirmation: best design rerun with num_models=5, num_recycle=6; returned same rank-1 envelope as triage.

### AF2 ranked representatives
| Rank | Sequence | ESM pLDDT | AF2 binder pLDDT | ipSAE | ipTM | pDockQ2 | Hotspot sat | BSA | Clash | PDB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | SALAHLQEAQYHAVLVADKTGDEALLAAVEAQDLERTLALLQQLVAQGLATADAQAAIAHLQEAL | 80.45 | 94.95 | 0.704 | 0.84 | 0.7995 | 100% | 1297.0 | 12.07 | /lambda/nfs/Daanishfiles/proteinclaw-home/gpu-workspace/9c46d4fd3ba5/alphafold2_multimer_22/complex_0cdaa3b838_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_000.pdb |
| 2 | MKVLTITAEALEDLFASLSDEELAAMLKTISEDFDKIRIVGEVKEEVLEKLKKLAKEAGIEVEVV | 79.95 | 92.01 | 0.410 | 0.72 | 0.5713 | 100% | 1293.5 | 19.00 | /lambda/nfs/Daanishfiles/proteinclaw-home/gpu-workspace/9c46d4fd3ba5/alphafold2_multimer_16/complex_f08b6119ff_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_000.pdb |
| 3 | AEEVAREYLARLEEILARAPSLSPEERREALEMARAVLEELEELGAAPEILERARAIVRELEALV | 80.52 | 90.97 | 0.218 | 0.61 | 0.1631 | not run | not run | not run | /lambda/nfs/Daanishfiles/proteinclaw-home/gpu-workspace/9c46d4fd3ba5/alphafold2_multimer_15/complex_aa57e11d82_unrelaxed_rank_001_alphafold2_multimer_v3_model_1_seed_000.pdb |

### Gate assessment
- Strict ProteinClaw hit gate: complex pLDDT >93 AND ipSAE >=0.93 AND ipTM >=0.7 AND hotspot satisfaction >=70% AND BSA >=~700 A^2.
- Hits: 0/8 strict hits. The rank-1 design passes pLDDT, ipTM, hotspot satisfaction, and BSA, but fails strict ipSAE (0.704 < 0.93).
- Practical interpretation: rank 1 is a credible ubiquitin Ile44-patch lead candidate for further in-silico refinement, not a strict hit. Round 2 should use partial diffusion or expanded polar-neighbor constraints around Q40/R42/H68/R72 to improve ipSAE and orientation specificity.

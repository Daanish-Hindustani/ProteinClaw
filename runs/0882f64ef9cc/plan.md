# ProteinClaw run 0882f64ef9cc - TREM2 minibinder

## Round 1 - hypothesis setup

### Target resolution
- Target: human TREM2, UniProt Q9NZC2, 230 aa. UniProt annotates the Ig-like V-type domain at residues 29-112.
- Structure: PDB 6Y6C, 2.26 A X-ray, TREM2 extracellular domain in complex with an scFv (Zhao et al., MAbs 2022, PMID 35921534, DOI 10.1080/19420862.2022.2107971).
- Chain/crop: chain A residues 20-137. Chain A has gaps 138-200 and 202-300 after the TREM2 ectodomain segment; crop 20-137 is 118 residues and avoids both gaps.

### Scout hypotheses
- Scout 1, prior TREM2 binders: weak retrieval. It found the required tools but returned mostly irrelevant PubMed/LitSense hits, so I did not treat it as evidence except to flag that direct due diligence was needed.
- Scout 2, IgV fold/topology: weak retrieval. It surfaced only a general scaffold-design criterion favoring soluble, low-cysteine protein scaffolds (PMID 33514045) and did not retrieve TREM2-specific fold evidence.
- Scout 3, developability liabilities: weak retrieval. It did retrieve that R47H reduces APOE/TREM2 functional binding in a literature passage (PMID 30229991) but otherwise returned unrelated evidence.

### Due diligence
- Direct PubMed query `TREM2 extracellular domain scFv 6Y6C` found the 6Y6C anti-TREM2 antibody paper: Zhao et al. 2022, PMID 35921534.
- Direct PubMed query `TREM2 R47H ApoE binding extracellular domain` returned multiple R47H/APOE/TREM2 papers, supporting R47 as biologically meaningful but not automatically the best design hotspot for this pipeline.
- Structural sandbox on full 6Y6C measured heavy-atom contacts within 4.5 A from TREM2 chain A crop 20-137 to non-target chains. The scFv/lateral-face contact residues included A54, A57, A59, A56, A58, A60, A102, A116, A127, A55, A62, A105, A103, A107, A125, A129, and A130.
- The same sandbox found exposed hydrophobic/aromatic residues on the TREM2 crop: A41 Met, A44 Trp, A69 Leu, A70 Trp, A71 Leu, A74 Phe, A75 Leu, A78 Trp, A89 Leu, A132 Pro, A133 Leu.
- Learned TREM2/IgV evidence from prior ProteinClaw runs is strong: unconditioned RFD3 repeatedly produced productive alpha-helical bundle binders on the apical CDR2 ridge, especially hotspots A44/A74/A76/A78, while 6Y6C/VHB937-like lateral-face hotspots folded but failed to dock (reported ipSAE ~0.014-0.250 on the lateral face vs ~0.75-0.84 on the apical ridge).

### Debate log
- Contested claim: Should this round copy the 6Y6C scFv lateral face because it is measured in the co-crystal, or target the learned/apical CDR2 hydrophobic ridge because the current RFD3 wrapper has prior success there?
- DEFEND challenge result: the research scout failed to retrieve useful TREM2-specific defense evidence and LitSense rate-limited. This did not overturn the sandbox plus learned-run evidence.
- Adjudication: apical CDR2-ridge wins. The 6Y6C co-crystal face is real but prior ProteinClaw evidence says it is structurally undockable with unconditioned RFD3, while the ridge has repeated productive helical-bundle designs. The decisive evidence is the learned TREM2 run history, corroborated by this run's exposed hydrophobic/aromatic patch around W44/F74/W78.

### Chosen design hypothesis
- Design an 85-95 aa soluble alpha-helical minibinder against TREM2 chain A crop 20-137, targeting the apical CDR2-ridge hotspots `A44,A74,A76,A78`.
- Hotspot atoms: W44 `CG,CD1,NE1`; F74 `CG,CD1,CD2`; R76 `CZ,NH1,NH2`; W78 `CG,CD1,NE1`.
- RFD3: cold-start, `num_designs=8`, `binder_length=85-95`, PPI defaults (`step_scale=3`, `gamma_0=0.2`, non-loopy). Rationale: one-round budget, known productive epitope, but TREM2 is a difficult IgV apex with a known ipSAE ceiling, so use the upper end of the easy/co-crystal band.
- ProteinMPNN: soluble model, 4 sequences/backbone, T=0.1. Rationale: keep AF2 funnel manageable at 32 sequences while sampling enough sequence diversity for a one-round run.
- ESMFold: batch all 32 sequences; retain pLDDT >= 70.
- AF2-multimer: rank survivors by binder-chain complex pLDDT with ipSAE/ipTM as interface read; run confirmation pass on the best candidates if enough survive.

### Round 1 - pipeline blocker
- RFD3 attempt 1 used the exact host path returned by `data.pdb_fetch`: `/home/ubuntu/.proteinclaw/gpu-workspace/0882f64ef9cc/pdb_fetch_1/6Y6C_chainA_crop20-137.pdb`. The tool rejected it with `target_pdb must live under /workspace/`.
- RFD3 retry used the inferred container path `/workspace/0882f64ef9cc/pdb_fetch_1/6Y6C_chainA_crop20-137.pdb`. The tool wrote that path into `/home/ubuntu/.proteinclaw/gpu-workspace/0882f64ef9cc/input.json` but returned `target PDB not found`.
- Hermes shell confirms `/workspace` is not visible in this run shell, while the crop exists only at the host GPU-workspace path. Per no-retry-loop rules and the one-round budget, the design pipeline stops before backbone generation. No RFD3 backbones, ProteinMPNN sequences, ESMFold monomers, AF2 complexes, interface metrics, `result.json`, or `report.html` were generated.
- Final hypothesis remains: TREM2 chain A crop 20-137, hotspots `A44,A74,A76,A78`, 85-95 aa alpha-helical minibinder, soluble MPNN T=0.1, but execution is blocked by the RFD3 path-mount mismatch.

### Round 1 - blocked retrospective
- **Worked:** Target resolution, research/debate, and hotspot selection converged on the established TREM2 CDR2-ridge strategy.
- **Why:** The crop is gap-free and prior ProteinClaw TREM2 evidence strongly supports the apical W44/F74/R76/W78 ridge over the 6Y6C lateral scFv face for unconditioned RFD3.
- **Gap:** Backbone generation could not start because `data.pdb_fetch` returned a host GPU-workspace path that RFD3 rejects, while the inferred `/workspace` path is not mounted/resolvable for RFD3 in this run.
- **Next hypothesis:** Re-run the same design hypothesis after fixing the `/workspace` mount/path alias between `data.pdb_fetch` and `design.rfdiffusion3`; do not change target, crop, hotspots, or length based on this failed execution.

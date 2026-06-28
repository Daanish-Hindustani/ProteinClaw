# ProteinClaw plan: TREM2 minibinder

## Round 1 research and due diligence

Target: human TREM2, UniProt Q9NZC2, 230 aa. Extracellular Ig-like V-type domain annotated at residues 29-112. RCSB search selected PDB 6Y6C, TREM2 extracellular domain in complex with scFv-4, 2.26 A X-ray structure. Chain A contains the TREM2 crop 20-137 as a contiguous modeled segment; gaps begin after 137, so the crop avoids missing residues.

Research evidence:
- PMID 34233201 / PMCID PMC8575122 reports structural characterization of anti-TREM2 scFvs that reduce shed ectodomain; 6Y6C is the highest-resolution available co-crystal found for this target class.
- LitSense passages from PMCID PMC12996653 and PMCID PMC12519512 describe TREM2 ligand-recognition surfaces: a hydrophobic apical site associated with ApoE/Abeta binding, a contiguous basic lateral site, and a distinct multimerization site.
- Literature passages identify hydrophobic-site mutations L69D/L71D/F74D and disease-linked/basic residues including R47H/R62H, with R76-W78 implicated in shifted interactions/multimerization contexts.

Structural sandbox:
- Heavy-atom contacts within 4.5 A from TREM2 chain A to scFv chains C/D in 6Y6C place the strongest co-crystal contact residues at A55, A59, A103, A56, A116, A57, A127, A62, A107, A58, A54, A60, A102, A130, A125.
- Exposed hydrophobics on the crop include M41, W44, L69, W70, L71, F74, L75, W78, L89, L129, L133. This supports the alternate ligand-site hypothesis but not as directly as the co-crystal interface for a protein binder.

Debate/adjudication:
- Contested claim: target the ligand hydrophobic/basic site versus recapitulate the anti-TREM2 scFv co-crystal face. The scFv face has direct protein-protein geometry, but learned TREM2 ProteinClaw runs report that this lateral/scFv-style face is functionally undockable with unconditioned RFD3 (folds OK, docks wrong; ipSAE near zero to 0.25), while the CDR2 hydrophobic ridge reliably gives ipSAE ~0.75-0.84 helical-bundle binders. The TREM2-specific learned evidence wins.
- Contested claim: use broad 5-hotspot IgV apex hints versus sparse CDR2-ridge hints. Learned runs show peripheral A47/A98 hotspots are consistently missed, and the practical rule is to use the 4-residue CDR2/CDR1 hydrophobic ridge {W44,F74,R76,W78}. Use those four hotspots for this single round.

Chosen design hypothesis:
- Chain/crop: 6Y6C chain A, residues 20-137.
- Hotspots: A44,A74,A76,A78. Rationale: TREM2-class learned skill plus current SASA check identify W44/F74/R76/W78 region as the contiguous designable hydrophobic/basic ridge; all residues are within the gap-free crop.
- Binder length: 90 aa, within the learned TREM2 sweet spot of roughly 80-95 aa and the canonical minibinder 60-100 aa range.
- RFD3: cold-start de novo, num_designs=8 because this is a one-round run and prior TREM2 campaigns needed broad cold-start sampling; PPI defaults step_scale=3/gamma_0=0.2/is_non_loopy=true.
- ProteinMPNN: soluble model, num_sequences=3 per backbone, sampling_temp=0.1.
- ESMFold: batch all sequences; retain pLDDT >= 70.
- AF2-multimer: rank survivors with colabfold MSA, num_models=1, then confirmation pass on top candidates with num_models=5 if viable.

### Round 1 — planned cold start
- **Worked:** pending pipeline results
- **Why:** pending pipeline results
- **Gap:** pending pipeline results
- **Next hypothesis:** no additional design round available by budget ceiling; final report will use confirmation metrics where possible.

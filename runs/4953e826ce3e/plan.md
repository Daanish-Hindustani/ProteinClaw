# Run plan & reasoning — TREM2 IgSF binder design

**Target:** human TREM2 V-type Ig-like ectodomain.
**PDB:** 5ELI chain A; gap inspector reports residues 20-201 present but gap 132-200 (stalk + His-tag tail unmodeled). **Crop = 20-131** (matches prior learned-skill validated crop; entirely gap-free; 112 residues; cropped PDB written by `data.pdb_fetch`).
**User goal:** ipSAE ≥ 0.88; ranking metric ipSAE; ≤ 250 aa; in-vitro BLI; VHB937-like stabilization mechanism (IgSF domain, NOT stalk).
**Budget:** 4 rounds (hard).

## Prior-art (mandatory pre-read)
- `NOTES.md` + `skills/learned/ig-v-flat-face.md` (5 dated blocks on this exact target).
- **Empirical ceiling on this pipeline:** ipSAE 0.84 (run `2e5ffd821473`, confirmed). The user-requested 0.88 exceeds the unconditioned-RFD3 architectural ceiling on the TREM2 CDR2 ridge. Will spend the full budget pushing on it honestly; will flag the gap explicitly in the final report.
- The lateral βA/F/G face (true VHB937 epitope) was tested in run `29c9603ba01d` → ipSAE 0.014/0.015/0.250 (folded, did not dock). The current RFD3 wrapper has no β-strand conditioning; helical bundles cannot engage flat β-sheet edges. Documented in learned-skill (f).
- The achievable epitope on this target with this toolset is the **CDR2 apical hydrophobic ridge (W44, F74, R76, W78)** — agonist precedent (Ellwanger 2021 PMID 35019161 aa 30-63, Chen 2026 PMID 41731491 M41-W44/L89) shows apical binders also stabilize TREM2 (increase soluble TREM2). So we satisfy the user's stabilization mechanism via the CDR2-ridge epitope, not the strict VHB937 lateral face.

---

## Round 1 — research, debate, hypothesis

### Scouts (`research` subagent, parallel)
1. **Epitope precedent (TREM2 IgSF binders).** Concluded: lateral βA/F/G face has the best co-crystal precedent (6YYE/6Y6C, scFv-2/-4 KD ~1 nM); confidence med-high. PMIDs: 34233201, 41731491, 35019161, 39333507. Apical CDR2 face also validated (03O05 agonist).
2. **IgV fold designability + topology.** Concluded: mixed α/β with β-strand pairing via strand-conditioned RFdiffusion v1 (Sappington 2025 PMC12852815, 5× hit-rate). Without strand conditioning, length 60-130 aa helical bundle (Watson 2023) is the fallback. Confidence med.
3. **Developability / in-vitro filters.** BindCraft cascade thresholds (Pacesa 2025 PMID 40866699): pLDDT > 0.80, ipTM > 0.50, ipAE < 0.35, length 50-80 aa, net charge ~−7, surface hydrophobicity < 35%; soluble_mpnn preferred. ipTM is a binary pass/fail gate, not a continuous Kd predictor (Bennett 2023 PMID 37149653).

### Debate & adjudication
- **Contested:** Scout 1 (lateral βA/F/G is best) vs. prior empirical run `29c9603ba01d` (lateral face produced ipSAE 0.014–0.25). **Scout 1 overturned** by stronger evidence — the antibody co-crystal precedent isn't reachable with helical-bundle RFD3 outputs; without strand conditioning, flat β-sheet edges yield non-docking designs. Apical CDR2 ridge is the achievable epitope class.
- **Contested:** Scout 2 (mixed α/β + strand pairing) — strand-conditioned RFdiffusion v1 is unmaintained in our wrapper (RFD3 has no SS/ADJ levers; NOTES.md 2026-06-07 deep-research block confirms this). Fallback: HHH/HHHH helical-bundle binders, 80-95 aa per learned skills (b)–(j).
- **Contested:** Scout 3 length 50-80 aa vs. learned skill (j) — length-106 cold-starts FAILED on this target (max ipSAE 0.786). Skill (j) wins: stick to 80-95 aa sweet spot.

### Round 1 design hypothesis
- **Epitope:** CDR2 apical hydrophobic ridge — 4 hotspots `A44,A74,A76,A78` (W/F/R/W). Reproduces the configuration that produced ipSAE 0.82 (run `29d98715cdb4`) and 0.84 (run `2e5ffd821473`).
- **Topology:** α-helical bundle (RFD3 default; HHH/HHHH). No conditioning.
- **Length:** 80-95 aa (80 lower bound to leave room for a longer-helix variant; matches `29c9603ba01d` recipe).
- **RFD3:** `num_designs=16`, default PPI params (step_scale=3, gamma_0=0.2, is_non_loopy=true). Default hotspot atoms (CA,CB).
- **MPNN:** `use_soluble_model=true`, model `v_48_020`, `sampling_temp=0.1`, `num_sequences=4` per backbone → 64 sequences.
- **ESM:** batch-fold all 64; keep monomer pLDDT ≥ 70.
- **AF2:** colabfold MSA, num_models=1, num_recycle=3 — triage scan. Top survivors only (limit ~12-16 jobs).
- **Goal:** establish baseline ipSAE (expected 0.78-0.82); confirm pipeline reproducibility; identify the best parent backbone for R2 partial diffusion.

Budget check: round 1 of 4.

---

## Round 1 — results

| rank | idx | BB | binder seq prefix | complex pLDDT | ipSAE | ipTM | pdockq2 | BSA | hotspot |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | BB2 | MAEELIRQAEKK… | 96.0 | **0.708** | 0.84 | 0.808 | 1641 | 75% (A44 missed @10.2Å) |
| 2 | 1 | BB0 | TLEELDRAFCLE… | 95.6 | 0.665 | 0.83 | 0.780 | 1694 | 50% (A76/A78 missed) |
| 3 | 9 | BB2 | MAEKLVEEAEEE… | 95.4 | 0.678 | 0.81 | 0.758 | 1622 | 75% (A44 missed @10.9Å) |
| 4 | 31 | BB7 | GVTSVSTLKVPA… | 93.5 | 0.592 | 0.78 | 0.657 | – | – |
| 5 | 7  | BB1 | VKLSPEEAAALA… | 90.4 | 0.574 | 0.76 | 0.557 | – | – |
| 6 | 41 | BB10 | SAVEEAQARAV… | 93.1 | 0.556 | 0.75 | 0.579 | – | – |
| 7 | 56 | BB14 | MAEERLAALAR… | 88.5 | 0.243 | 0.53 | 0.244 | – | – |
| 8 | 49 | BB12 | TAEEYRLLADL… | 89.8 | 0.207 | 0.47 | 0.204 | – | – |
| 9 | 12 | BB3 | SAAVEALLAAT… | 83.9 | 0.016 | 0.25 | 0.055 | – | – |

### Round 1 — partial-helix bundles win on CDR2 ridge; ceiling 0.708
- **Worked:** BB2 (CDR2 ridge helical bundle, 86 aa) dominated — top 1 and top 3 both came from this single backbone, both at ipSAE > 0.67 with ipTM ≥ 0.81 and 75% hotspot satisfaction. The bundle docks across CDR2 W44/F74/R76/W78 with A74/A76/A78 satisfied and A44 the periphery miss at min Cβ ~10.2 Å.
- **Why:** the CDR2 hydrophobic patch (W44 + L71/F74/R76/W78) is the deepest contiguous non-polar surface on the IgSF apex; helical bundles place their amphipathic face against it. Identical pattern to learned skills (b)/(c)/(i).
- **Gap:** ipSAE 0.708 vs the user-requested ≥ 0.88 gap of 0.17. A44 is the limiting hotspot — its CD2 reach is ~0.2 Å short of the 10 Å satisfaction cutoff. Even the prior-best 0.84 (run 2e5ffd821473) sat well below 0.88.
- **Next hypothesis (R2):** partial_t=3 Å polish on the BB2 idx-10 winner — learned skill (g) shows this is the reliable 0.75 → 0.80 lift for this geometry, and pushes A44 a fraction closer (might cross the 10 Å threshold). Use the same hotspot list to keep selection pressure on A44; soluble MPNN T=0.05 to lock down low-noise sequences on the polished backbones.

Budget check: round 2 of 4.

---

## Round 2 — research, debate, hypothesis

### Research (per-round mandate)
Round-1 evidence updates: BB2 helical bundle reproduces the documented 0.7+ regime; A44 the only sub-threshold hotspot at 10.2 Å (just out of cutoff). Hypothesis from R1 is **a small geometric perturbation toward A44 should close the gap to 0.75-0.80, perhaps push BSA up**.
Targeted scout call routed to lit-search (filter-safe).

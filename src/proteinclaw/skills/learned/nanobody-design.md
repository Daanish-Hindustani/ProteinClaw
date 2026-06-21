# Skill: nanobody (VHH) binder design

This file covers **what changes** when designing nanobodies (single-domain camelid antibody
fragments, VHH / Nb) versus generic de novo mini-binders. Read this before any run where
the user's prompt mentions "nanobody", "VHH", "single-domain antibody", or "camelid".

Primary source: Zhao, Yilmaz, Lee et al. 2026 (bioRxiv 10.64898/2026.04.13.717816) —
"Agent-Guided De Novo Design of Nanobody Binders Against a Novel Cancer Target."
288,000 designs → 39.7% SPR hit rate (46/116), KD 0.66–305 nM median 31.7 nM, against
a DSRCT target with no experimental structure and no prior antibody data. The most
comprehensive publicly validated nanobody de novo design workflow to date.

Append-only; corrections start with `Correction:`.

---

## CRITICAL: our pipeline is NOT nanobody-specific — flag this upfront

The `proteinclaw` pipeline was built for **generic de novo mini-binders**:
RFdiffusion3 → ProteinMPNN → ESMFold → AF2-multimer.

**RFD3 is not an antibody-specific tool.** It will not reliably produce the VHH Ig
β-sandwich scaffold. At 115–130 aa with concave hotspots, RFD3 sometimes generates
compact β-structures, but this is not guaranteed and is architecturally different from
what dedicated tools do.

**The state-of-the-art nanobody-specific generative tools are:**

| Tool | Approach | Notes |
|---|---|---|
| **RFantibody** | Diffusion-based CDR backbone generation on fixed VHH framework | Hotspot-conditioned; known index-offset bug in hotspot conditioning (see §3 below) |
| **IgGM** | Joint CDR sequence + structure diffusion | Best median affinity in Zhao 2026 (n=33, median KD 28.0 nM) |
| **mBER** | Backpropagation through AF-Multimer; gradient-optimized CDR sequences | No diffusion; fewer binders (n=13, median 43.9 nM) but complementary sequence space |
| **BindCraft** | AF2-hallucination loop; general binder | Works for VHH-like outputs but not VHH-scaffold-constrained |

**None of these are currently wired into the `proteinclaw` MCP tool set.** When a user
asks for nanobody design and expects a genuine VHH scaffold:
1. **State the limitation explicitly** — the pipeline can attempt nanobody-like binders with
   RFD3 at 115–130 aa, but cannot guarantee the Ig scaffold or CDR-loop architecture.
2. **Recommend** the user run RFantibody / IgGM / mBER outside this pipeline for a genuine
   nanobody campaign, then import the resulting sequences for scoring with ESMFold / AF2.
3. **If the user accepts the limitation**, proceed with RFD3 as a generic binder diffuser
   using the adapted parameters below — the binding biology is still informative.

---

## What is a nanobody and why it matters for this pipeline

Nanobodies are ~115–130 aa single-domain antibody fragments (the VHH domain). Their binding
interface is dominated by three hypervariable loops — **CDR1** (~5–10 aa), **CDR2** (~4–6 aa),
and **CDR3** (longest and most variable, 6–24 aa; forms a protruding finger). Unlike Fab
arms, VHH CDR3 can protrude into enzyme active sites, ion-channel pores, and concave epitopes
inaccessible to conventional antibodies.

**Structural differences that affect every pipeline stage:**

| Property | Generic de novo mini-binder | Nanobody (VHH) |
|---|---|---|
| Length | 60–130 aa | 115–130 aa (fixed β-scaffold) |
| Fold | Agent-chosen (helix bundles, HHH) | Ig-V β-sandwich scaffold + 3 CDR loops |
| Binding mode | Helix / loop packs against flat surface | CDR3 finger protrudes into cavity / concavity |
| Best epitopes | Flat surfaces, ridges, hydrophobic patches | Concave cavities, enzyme active sites, cleft epitopes, recessed loops |
| Framework | Agent-chosen | **Must fix a VHH framework scaffold; only CDRs are designed** |
| CDR3 length | N/A | Vary 6–13 aa — longer loops reach deeper into cavities |

---

## 1. Target selection: prefer concave / cavity epitopes

VHH CDR3 excels on:
- **Enzyme active sites** (kinases, proteases, GTPases) — CDR3 protrudes into the catalytic cleft
- **Receptor ligand-binding pockets** (GPCRs, RTK extracellular domains)
- **Recessed loops** and canyon-shaped epitopes inaccessible to conventional Ab Fab arms
- **Allosteric pockets** that gate a conformational change

If the target is a flat surface already covered well by helical-bundle binders (Ig-V β-sheet
faces, linear epitopes on PPI surfaces), a generic mini-binder may outperform a nanobody with
the current pipeline.

---

## 2. Hotspot identification — use a broad multi-evidence agent strategy

**Key finding (Zhao 2026):** On a novel target with no prior antibody data, the paper's hotspot
recommendation agent achieved **~80% top-5 accuracy** (holdout n=76) by integrating 7
deterministic tools and synthesizing with an LLM. The strategy was **broad coverage over narrow
precision** — the cost of missing a viable epitope outweighs the cost of testing extra candidates.

### Tools the agent integrated (replicate these in your structural sandbox):

1. **Unique-regions analysis** — align target against user-specified negative controls (off-targets
   you must NOT bind); recommend only regions unique to the positive target. Run as a SASA +
   pairwise sequence alignment in Bash scratch.

2. **IEDB epitope database** — align target sequence against known B-cell epitopes from the Immune
   Epitope Database. Use relaxed E-value thresholds (default thresholds penalize short sequences;
   most conformational epitopes are discontinuous short fragments).
   - `research.literature_search("IEDB epitope <target name>")` + `WebSearch` for IEDB directly.

3. **PFAM domain annotation** — identify functional domain boundaries (kinase domain, ligand-binding
   domain, etc.). Regions within functionally critical domains are higher-priority hotspot candidates.
   - `research.literature_search("<target name> PFAM domain functional residues")`.

4. **SASA** — per-residue solvent accessibility (biopython Shrake-Rupley in Bash scratch).
   Surface-exposed residues only; buried residues cannot be hotspots.

5. **Secondary structure** — loop / β-turn regions are overrepresented in known epitopes vs buried
   helical segments. Classify helix / sheet / coil in Bash scratch.

6. **Hydrophobicity profiling** — identify hydrophobic patches (drive binding affinity at the
   interface core) and flanking hydrophilic regions (specificity). Zh 2026: Hotspot B selected for
   90% surface accessibility + cysteine content; Hotspot G for location in a functionally critical
   domain + favorable charged residue composition.

7. **Interface contacts** (if a complex PDB exists) — compute contacts within 5 Å across chains.
   **Remove existing antibody chains before computing SASA / secondary structure** on the target, or
   their presence will artificially reduce surface accessibility scores at the real binding interface.

### How many hotspot regions?

Zhao 2026 used **8 non-overlapping 10-residue regions**. Binders from ALL 8 hotspot-conditioned
design groups were recovered by SPR. This argues for breadth (≥6 regions) over narrow precision,
especially against novel targets.

Practical recommendation for our pipeline: define **3–8 hotspot regions** covering different faces
of the target. Pass one hotspot to each RFD3 / design call to distribute the design budget.

### Discontinuous epitopes — expect and exploit them

Zhao 2026 found that Hotspots B, F, and G form a **spatially contiguous binding surface** despite
being defined as separate regions. Designs conditioned on one hotspot frequently engaged a neighboring
hotspot in Boltz-2 co-folding. The lowest-KD binders (e.g. PRJ266_080, 2.38 nM) engaged the
combined B+G discontinuous surface. This is not a failure — it reveals higher-order epitope
architecture. When post-AF2 analysis shows designs from different hotspot conditions engaging
overlapping residues, treat this as evidence of a productive discontinuous epitope worth targeting
directly.

---

## 3. Generative methods — what to use and their trade-offs

If running within the `proteinclaw` pipeline (RFD3 only):

- Set `binder_length="115-130"` to match VHH length.
- Use `num_designs=12–20` (larger funnel than mini-binders — CDR3 loop diversity needs more samples).
- Acknowledge the scaffold is not guaranteed to be VHH.

If the user can run external tools and import sequences for scoring:

### RFantibody
- Diffusion-based CDR backbone generation on a **fixed VHH framework scaffold**.
- Hotspot-conditioned via soft constraints.
- **Known issue (Zhao 2026):** an index offset bug in hotspot conditioning introduced systematic
  positional errors that disproportionately affected median designs. Top candidates overcame this
  through superior overall geometry. **Practical consequence:** use RFantibody but expect lower
  median in-silico scores vs IgGM/mBER; evaluate TOP percentile, not median.
- All 3 RFantibody-produced SPR binders had low Rmax (<30 RU) in Zhao 2026 — high KD uncertainty.
- Use both **vanilla ProteinMPNN AND AbMPNN** for sequence design within RFantibody:
  AbMPNN showed higher median predicted binding affinity than vanilla ProteinMPNN (Zhao 2026).

### IgGM
- Joint CDR sequence + structure diffusion.
- **Best performer:** n=33 confirmed binders, median KD 28.0 nM (Zhao 2026).
- Input: fixed VHH framework with CDR residues masked + antigen structure. Output: complete CDR I-III.
- Vary CDR H3 length 6–13 aa and random seeds per design run.

### mBER
- Backpropagation through AF-Multimer; gradient-optimized CDR sequences (no diffusion).
- n=13 confirmed binders, median KD 43.9 nM (Zhao 2026); difference from IgGM not significant (p=0.311).
- Explores different sequence space from IgGM — use both for complementary diversity.
- Same fixed VHH framework input as IgGM.

**Use all three in combination.** They produce non-overlapping sequence sets; shared failure modes
from any single method are mitigated.

---

## 4. VHH framework selection — critical design parameter

**The most impactful single variable in Zhao 2026:** Framework B accounted for **45/46 high-signal
confirmed binders** (Rmax ≥ 30 RU). The distribution was not uniform — one framework dominated.

**Practical rules:**
- Always diversify across **≥3 distinct VHH frameworks** when designing. Do NOT run all designs on
  a single scaffold.
- Common VHH frameworks: humanized llama VHH (e.g. Nb6, Nb7 used in published BindCraft campaigns),
  synthetic frameworks (e.g. Sdab-H11, cAbBCII10), camelid consensus frameworks. Search the SAbDab
  (Structural Antibody Database) for VHH crystal structures to use as framework templates.
- Framework-dependent effects on in-silico metrics exist (Zhao 2026): certain scaffolds consistently
  outperform others in predicted binding metrics. If scoring shows one framework dominates early,
  bias subsequent design rounds toward it — but do not abandon others until experimental data confirms.
- **You cannot know ahead of time which framework will win.** Framework B's dominance in Zhao 2026
  was not predicted by any in-silico metric — it was discovered by experimental validation. Budget
  for this uncertainty by diversifying early.

---

## 5. CDR3 loop length variation

Vary **CDR H3 length from 6–13 aa** as a combinatorial design parameter (Zhao 2026 used 4–13;
6–13 is the productive range). Longer CDR H3 loops (10–13 aa) exhibit greater sequence diversity
and can reach deeper into cavities. Shorter loops (6–9 aa) are more constrained and better for
shallow epitopes. Sample multiple lengths per hotspot + framework combination.

---

## 6. Target structure — use multiple folding models for novel targets

When no experimental structure exists:

- Generate predicted structures using **multiple folding methods**: AlphaFold2, Boltz-2 (with and
  without `use_potentials`), Chai-1. In Zhao 2026, all pairs exceeded TM-score 0.5 (same overall
  fold); Boltz-2 variants and Chai-1 formed a tight cluster (TM 0.78–0.91); AlphaFold2 was most
  divergent (TM 0.62–0.66).
- Design against **multiple predicted conformations** to reduce risk of overfitting to structural
  artifacts. Sequences robust to conformational variability are more likely to bind the real target.
- Practical: use `data.pdb_fetch` if an experimental structure exists; otherwise instruct the user
  to generate structures with AlphaFold2 DB + at least one other method (Boltz-2 / Chai-1) and
  import PDB files into the session workspace.

---

## 7. Scoring and filtering — structural metrics are weak predictors; sequence metrics matter more

**Critical finding (Zhao 2026, Figure S7):** In SPR-confirmed binders vs non-binders (n=116):
- **Boltz-2 ipTM, ipLDDT, NanobodyBuilder2 pLDDT: NO significant discrimination** (Mann-Whitney
  p not significant). These structural confidence scores do NOT reliably predict experimental binding.
- **MochiBind (sequence-based ESM2 affinity predictor): p = 0.0227** — the ONLY metric with
  statistically significant discrimination. Even so, the effect is modest.
- **Minimum CDR-antigen distance from Boltz-2 co-folding**: useful for hotspot adherence
  verification but similarly weak as a binding predictor.

**Practical consequences:**
- Do NOT apply tight ipTM or pLDDT cutoffs as a primary filter. A high ipTM does not mean the
  design binds; a low ipTM does not mean it doesn't. (This contrasts with mini-binder guidance
  where AF2 complex_confidence is the primary ranking signal — for nanobodies against novel targets,
  that signal is weaker.)
- Use **multi-objective Pareto optimization** rather than a single composite score. The Zhao 2026
  pipeline selected across 5 objectives simultaneously (monomer pLDDT, complex ipTM, complex
  ipLDDT, sequence-based affinity, minimum CDR-antigen distance) and took the first 9 Pareto
  fronts. This preserves candidates that excel on different metric combinations rather than
  collapsing to one axis.
- **ESM2-based sequence affinity predictors** (like MochiBind) provide orthogonal signal
  independent of structural modeling. If any such tool is available, use it as a scoring input.
- The implication for our pipeline: `complex_confidence` (AF2 binder-chain pLDDT) is still
  useful for ranking but should NOT be the sole filter. Apply a lenient threshold (>80, not >90)
  and rely on diversity rather than tight ipSAE gating.

---

## 8. Hotspot adherence validation via independent co-folding

After designing against a hotspot, use **Boltz-2 (or AF2-multimer) co-folding from sequence
alone** (without hotspot knowledge) to verify that hotspot specificity is encoded in the
designed sequences:
- Co-fold the antibody + antigen sequences.
- Compute CDR heavy-atom contacts within 7 Å of antigen heavy atoms.
- A design conditioned on Hotspot F should show elevated contact frequency near Hotspot F in
  the independent co-folding.

Zhao 2026 found that **Hotspots F, G, H achieved high peak CDR contact frequencies** at
intended epitopes, confirming that epitope specificity from backbone generation is preserved
through independent structure prediction. If your co-folded contacts consistently land far from
the conditioning hotspot, the backbone generation failed to encode specificity — those designs
are lower priority.

Run this as a Bash scratch script via Biopython NeighborSearch on co-folded PDB files.

---

## 9. ProteinMPNN for nanobody sequence design (within the proteinclaw pipeline)

When using ProteinMPNN on RFD3-generated backbones for a nanobody campaign:

- **`sampling_temp=0.2–0.3`** — CDR loops are inherently flexible; higher temperature allows
  more sequence diversity at the CDR positions than the 0.05–0.1 used for polished helical bundles.
- **`use_soluble_model=true`** — same rationale as generic binders (fewer exposed apolar
  residues; Bennett 2023 / BindCraft).
- **Consider AbMPNN over vanilla ProteinMPNN if available.** Zhao 2026 found AbMPNN-designed
  sequences showed higher median predicted binding affinity than vanilla ProteinMPNN within
  the RFantibody pipeline. AbMPNN is trained specifically on antibody sequences.

---

## 10. AF2-multimer scoring caveats for nanobodies

The standard quality gate (ipSAE ≥ 0.93, complex pLDDT > 93) was calibrated for generic
mini-binders on well-characterized targets. For nanobody campaigns against novel targets:

- **Apply a lenient triage gate first**: complex pLDDT > 80, ipSAE > 0.3. The Zhao 2026
  data shows that even designs with modest structural scores can bind experimentally. Over-
  filtering eliminates real binders.
- **BSA caveat**: deep-pocket binders may show BSA 500–700 Å² (below the ≳700 Å² generic
  threshold). This is epitope-appropriate for cavity-engaging CDR3. Flag as "low BSA but
  cavity-epitope design" rather than a gate failure.
- **Hotspot satisfaction interpretation**: CDR3 protrusion into a cavity means the "hotspot"
  residues may be within the cavity interior. If hotspot satisfaction is low but complex pLDDT
  is high, the binder may have docked to a neighboring surface rather than the intended epitope
  — this is common and can still indicate genuine binding.
- **Confirmation pass (num_models=5)**: apply the same robustness-test logic as for mini-binders
  (it catches false positives, does not lift real scores). Use before reporting final candidates.

---

## 11. Developability and liability checks

Nanobodies have favorable inherent developability but CDR sequences can introduce liabilities:

- **N-linked glycosylation motifs** (NxS/T where x ≠ P) in CDRs or framework regions.
- **High-risk deamidation** (NG, NS motifs in CDR loops — prone to deamidation under storage).
- **Fragmentation sites** (DP, DG, TP, etc.).
- **Isomerization** (DS, DT in CDRs).
- **Cysteine bonds** — extra cysteines in CDR H3 can form disulfides that stabilize long loops
  (CDR H3 > 17 aa commonly does this in camelids) but complicate manufacturing if unpaired.
- **Oxidation** (Met, Trp in CDR loops).

Check these in Bash scratch (simple regex on CDR sequences) before advancing to experimental
validation. Zhao 2026 used the Liability Antibody Profiling (LAP) methodology for this
systematically across 288K candidates.

---

## 12. Hit rate expectations and campaign scale

From Zhao 2026 (the most rigorous published benchmark for de novo nanobody design):

| Stage | N | Notes |
|---|---|---|
| Generated | 288,000 | 3 methods × 3 frameworks × 8 hotspots × 5 structures × CDR3 lengths × seeds |
| Pareto-filtered for YSD | 100,000 | First 9 Pareto fronts across 5 objectives |
| YSD expression rate | 90.6% | Very high — VHH folds well in yeast |
| Advanced to SPR | 116 | Based on FACS MFI threshold after 2 rounds |
| Confirmed binders (Rmax ≥ 30 RU) | 46/116 (39.7%) | KD 0.66–305 nM, median 31.7 nM |
| Sub-nanomolar (KD < 1 nM) | 16 candidates | Includes some with Rmax < 30 RU (uncertain fits) |

**Our pipeline operates at much smaller scale** (~10–50 designs through AF2). Calibrate expectations:
- At 10–50 AF2-scored designs, expect 0–5 designs with ipSAE > 0.4 for a novel nanobody target.
- The ipSAE ≥ 0.93 strict gate is unrealistic for a first-round nanobody campaign against a novel
  target. Use the lenient gate above and report the best available.
- More than 1–2 rounds of nanobody campaign is warranted; the DBTL loop (Zhao 2026 §3) is
  the intended operating mode for serious nanobody discovery.

---

## 13. Summary checklist for a nanobody run

- [ ] **State the pipeline limitation**: RFD3 is not nanobody-specific; flag this and recommend
      dedicated tools (RFantibody, IgGM, mBER) if the user needs a true VHH scaffold
- [ ] Target has a concave / cavity epitope — if flat surface, consider mini-binder instead
- [ ] Hotspot identification: run SASA + secondary structure + hydrophobicity in Bash scratch;
      also check IEDB epitopes + PFAM domains via `literature_search`; target ≥ 6 regions
- [ ] Diversify across ≥ 3 VHH frameworks (cannot predict which will dominate pre-experimentally)
- [ ] `binder_length="115-130"` in RFD3 (or vary CDR H3 6–13 aa if using dedicated tools)
- [ ] `num_designs=12–20` (wider funnel)
- [ ] `sampling_temp=0.2–0.3` in ProteinMPNN; `use_soluble_model=true`
- [ ] After ESMFold: lenient pLDDT ≥ 70 threshold; check for β-strand/loop alternation (VHH sig)
- [ ] After AF2: use lenient triage gate (complex pLDDT > 80, ipSAE > 0.3); BSA < 700 Å² is
      acceptable for cavity epitopes; do NOT gate tightly on ipTM or pLDDT alone
- [ ] Boltz-2 (or AF2) hotspot adherence check: verify CDR contacts concentrate near conditioning
      hotspots in independent co-folding
- [ ] Liability check: regex for NxS/T (glycosylation), NG/NS (deamidation), extra cysteines in CDR
- [ ] Report: state explicitly whether any generated backbones resemble VHH fold vs helical bundle;
      flag if no VHH-fold backbone emerged and recommend dedicated tools for next cycle

---

## Key references

- **Zhao, Yilmaz, Lee et al. 2026** (bioRxiv 10.64898/2026.04.13.717816): primary source for this
  skill. 39.7% hit rate, 288K designs, novel DSRCT target, RFantibody + IgGM + mBER + YSD + SPR.
- **Bennett et al. 2023 (Nat Commun)**: BindCraft / soluble MPNN for de novo binders (framework).
- **Hamers-Casterman et al. 1993 (Nature)**: original camelid single-domain antibody discovery.
- **Desmyter et al. 2001 (Nat Struct Biol)**: VHH CDR3 protrusion into lysozyme active site.
- **NanobodyBuilder2**: specialized VHH structure prediction (used for monomer pLDDT scoring).
- **IgGM paper (2024/2025)**: joint CDR sequence-structure diffusion.
- **mBER paper (in review at time of Zhao 2026)**: backpropagation-guided CDR optimization.
- **RFantibody (Baker lab)**: diffusion-based antibody design.
- **SAbDab (Structural Antibody Database)**: source of VHH framework templates and validation set.
- **IEDB (Immune Epitope Database)**: B-cell epitope database used in hotspot recommendation.

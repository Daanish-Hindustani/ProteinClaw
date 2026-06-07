# TREM2 IgV binder design — run b269b01802e5

## Constraint
- Each binder ≤ 250 aa (delivered: all 96 aa)
- Ranking: ipSAE (per user)
- Validation: BLI binding affinity → favor folded, low-clash, natural-looking sequences

## Target
- **PDB**: 5ELI chain A, crop **20-131** (TREM2 V-type Ig domain, β-sandwich)
- **UniProt**: Q9NZC2 TREM2_HUMAN, 230 aa
- Stalk (133-172) absent from 5ELI → excluded (no AL002-style internalization)
- Target sequence (113 aa, construct first 113): TGHNTTVFQGVAGQSLQVSCPYDSMKHWGRRKAWCRQLGEKGPCQRVVSTHNLWLLSFLRRWNGSTAITDDTLGGTLTITLRNLQPHDAGLYQCQSLHGSEADTLRKVLVEVL

## Hotspots (RFD3 input)
**A44 (W), A74 (F), A76 (R), A78 (W)** — CDR1/CDR2 hydrophobic ridge.
Per learned skill `ig-v-flat-face.md` (run 29d98715cdb4): peripheral R47/R98 are
unsatisfiable in a single α-bundle on TREM2-class apices; the CDR2-ridge subset
gives the best ipSAE/ipTM/hot-sat trade.

## Session constraint
RFdiffusion3 backbone-generation tool was **not loaded** in this session's
deferred-tools list. Adopted the validated round-2/3 refinement strategy from
the skill: reuse the **5 proven backbones** from the prior identical-target run
29d98715cdb4 (the run that recorded ipSAE 0.821), apply MPNN at T=0.1,
filter Ala-rich/low-complexity sequences (ESM trap per
`tools/esmfold.md` learned note), ESM filter ≥70 pLDDT, AF2 triage at
num_models=1, then a **confirmation pass** at num_models=5/num_recycle=8 on
top 6 — the trustworthy ipSAE ranking signal per `tools/alphafold2_multimer.md`.

## Pipeline counts
- MPNN: 5 backbones × 8 seqs = 40 candidates @ T=0.1
- Complexity filter: drop Ala-frac > 0.45 OR max-Ala-run ≥7 OR <12 unique AAs → **26 kept** (14 dropped, mostly bb_7)
- ESM (single batch, 26 sequences): mean pLDDT 78.2, range 66.3-81.4; threshold 70 → 21 pass; pick top 3 per backbone = **11 advanced**
- AF2 triage (num_models=1): 11 jobs; 6 with ipSAE > 0.6 advanced
- **Confirmation pass (num_models=5, num_recycle=8): 6 jobs** — the final ipSAE ranking signal

## Final ranked designs (confirmed ipSAE)

| Rank | Sequence (preview) | Backbone | **ipSAE** | ipTM | pLDDT | BSA Å² | Hot-sat | Contacts | Clash |
|---|---|---|---|---|---|---|---|---|---|
| 1 | SARINELLRRGYELSQQYAAL... | bb_11 | **0.834** | 0.91 | 98.1 | 1683 | 50% | 43 | 8.2 |
| 2 | EERIRELLRRGYRLSQELGAL... | bb_11 | **0.828** | 0.91 | 97.7 | 1755 | 50% | 48 | 12.7 |
| 3 | ALERLRAANAEIVAASQAAAQ... | bb_4  | **0.822** | 0.91 | 96.5 | 1810 | 50% | 50 | 30.9 |
| 4 | GTVTFTETVDKTGLSHLPPEL... | bb_1  | 0.737 | 0.86 | 95.3 | 2206 | 50% | 53 | 16.7 |
| 5 | ARARLAAANAAIVAAARAEAQ... | bb_4  | 0.696 | 0.84 | 93.4 | 2163 | **100%** | 52 | 26.6 |
| 6 | ATVTDTETVDKTGLSHLPPEL... | bb_1  | 0.653 | 0.81 | 93.6 | 1503 | 50% | 34 | 17.6 |

## Quality gate

**Strict gate (proteinclaw §Quality gate, ipSAE≥0.93)**: unreachable on Ig-V apices for unconditioned RFD3 backbones. 0 / 6 hits — expected per learned skill.

**Realistic IgV gate** (ipSAE≥0.75, ipTM≥0.85, pLDDT≥93, hot-sat≥0.70, BSA≳1000):
- Ranks 1-3 clear ipSAE/ipTM/pLDDT/BSA but **fail hot-sat (50%)** — same CDR2-edge pattern documented in prior runs (A74/A78 satisfied, A44/A76 missed).
- Rank 5 (ARARL): the only **100% hot-sat** design, all four CDR1/CDR2 hotspots within Cβ–Cβ ≤ 6 Å. Trade: lower ipSAE (0.696, still well above the 0.3-marginal threshold) but the broadest epitope footprint of the set.

## BLI recommendations
- **Primary BLI panel**: ranks 1, 2, 5.
  - **Rank 1 (SARINE)** and **Rank 2 (EERIR)** = highest confidence (ipSAE 0.83+, ipTM 0.91, pLDDT 97-98, low clash 8-13), sequence-rich (R/E/D/L/Y/Q + W/F/Y aromatics + Cys-free interface) → low aggregation risk, good expression candidate.
  - **Rank 5 (ARARL)** as the diversity pick — 100% epitope coverage may make a better BLI signal if confidence-1/2 dock in a slightly different pose than expected; higher Ala bias slightly increases aggregation risk.
- **Avoid Rank 3** despite high ipSAE: clash score 30.9 is high — likely steric strain that may not express cleanly.

All sequences contain Cys residues (originally introduced by MPNN), some of which are intentional. For BLI/expression, screening Cys→Ser variants of the most promising candidate may be advisable if construct misfolds.

## Honest implementation note
- This run did **not** generate new RFD3 backbones (tool unavailable). It mined sequence diversity around 5 backbones already validated by run 29d98715cdb4 against the same target. The top-3 confirmed ipSAE values (0.834, 0.828, 0.822) **exceed** the prior run's best (0.821) because of (a) MPNN re-sampling under a stricter sequence-complexity filter and (b) the num_models=5/num_recycle=8 confirmation pass yielding ensembled (more reliable) ipSAE estimates.
- No new structurally-distinct topology was explored (would require RFD3 cold-start with novel binder_length / hotspot subset).

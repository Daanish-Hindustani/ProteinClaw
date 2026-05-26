# Tool skill: `design.rfantibody` — nanobody / scFv CDR design

Read this before pipeline **nanobody design step** (replaces step 4–5
for VHH / scFv campaigns). It is the operational detail for the
summary in the core skill.

`mcp__proteinclaw_tools__design_rfantibody`:
- `target_pdb`, `target_chain` — pre-cropped extracellular domain PDB
  (see "Membrane protein targets" below)
- `hotspot_residues` — 3–6 residues on target_chain (see "Hotspot
  selection" below — quality is the single biggest lever)
- `framework_type` — `"vhh"` (default) for single-domain nanobody;
  `"scfv"` for two-chain variable fragment
- `loop_lengths` — CDR length constraints, e.g. `"H3:15-22"`. For MOR
  the design spec requires `H3:15-22`; set it explicitly.
- `num_designs` — backbones for stage 1; × `seqs_per_struct` = total
  into RF2. See "Sizing" below.
- `pae_threshold` / `rmsd_threshold` — RF2 self-consistency filter.
  Defaults (10 / 2.0) are the RFantibody recommended values.

The tool runs the full 3-stage pipeline internally (RFdiffusion →
ProteinMPNN → RF2). **Do not call design.rfdiffusion3 or
design.proteinmpnn for the same design task** — they would duplicate
work and produce incompatible output.

---

## Hotspot selection — the most important input

RFantibody is **more hotspot-sensitive than standard RFdiffusion**.
Poorly chosen hotspots produce undocked designs or designs that bind
the wrong face. Before calling this tool:

1. Load the target PDB and identify the binding face from the
   literature / co-crystal context.
2. Pick 3–6 residues that are:
   - On the target face you want to block / engage.
   - Include at least 1–2 hydrophobic or aromatic residues (Phe, Trp,
     Tyr, Leu, Val) — these are the anchor contacts.
   - Avoid glycosylated residues (NXS/T motifs) and highly flexible
     loop termini.
3. Verify residues are on the `target_chain` specified (wrong chain →
   NormalizeError before the container even starts).
4. If the first run yields 0 filtered designs, revisit hotspot
   selection before increasing `num_designs`.

---

## Sizing the design funnel

| Campaign type | num_designs | seqs_per_struct | Into RF2 | Practical on A100 |
|---|---|---|---|---|
| Scout / sanity check | 10 | 4 | 40 | ~30 min |
| Standard round | 20 | 4 | 80 | ~1–2 h |
| Hard target / MOR | 50 | 4 | 200 | ~3–5 h |
| Full campaign | 200+ | 4 | 800+ | multi-GPU / multi-run |

The published RFantibody papers used 10,000+ designs with yeast display
validation downstream. On a single A100 with in-silico AF2 ranking,
50–200 designs through RF2 → top 5–10 to AF2 is the practical regime.
Be honest in your summary about the exploratory scale.

---

## After this tool: what to pass to AF2-multimer

Use `filtered_design_paths` (not `design_paths`) as input to
`structure.alphafold2_multimer`. The filtered PDBs have:
- Chain A = VHH nanobody (binder)
- Chain B = target (already the right layout for AF2-multimer)

Pass the sequence from `filtered_designs[i].sequence` as the binder
sequence for the AF2 call. Run AF2 on the top 5–10 filtered designs,
ranked by `rf2_pae` ascending (lower pAE = better self-consistency).

**Skip `structure.esmfold` for nanobody campaigns.** RF2 already
validated structural self-consistency; running ESMFold as a pre-filter
is redundant and slows the pipeline.

---

## Membrane protein targets (MOR, GPCRs)

AF2-multimer does not model the lipid bilayer. TM helices in the
target chain will be modelled in vacuum → depressed complex pLDDT
regardless of binder quality.

**Always pre-crop the target to the extracellular domain before
calling this tool.** For MOR:

- Inactive state (4DKL, chain A): retain approximately residues 84–230
  (ECL1, ECL2, ECL3, top of TM helices 2–5). Confirm exact residue
  numbers against the PDB ATOM records.
- Active state (6DDE, chain R): same principle; use the human MOR chain.

After AF2-multimer scoring, use **binder-chain pLDDT** (chain A only)
as the primary ranking signal, NOT complex pLDDT. The quality gate
thresholds (complex pLDDT > 85) are calibrated on soluble targets; for
membrane protein runs, a binder chain pLDDT > 80 with ipSAE ≥ 0.5
is a credible near-miss worth pursuing. State this clearly in your
triage narration and plan.md.

---

## Two-variant MOR design (agonist vs antagonist)

The Kobilka collaboration requires both variants. Run this tool twice,
once per template:

| Variant | Template | target_chain | Notes |
|---|---|---|---|
| Antagonist / inactive | 4DKL | A | Mouse MOR; use for backbone context |
| Agonist / active | 6DDE | R | Human MOR; preferred for final scoring |

The receptor sequence is identical between states; conformational
information comes entirely from the structural template. Use separate
`step` values (e.g. `step=0` antagonist, `step=1` agonist) so outputs
land in distinct directories.

---

## Developability filters (run in bash scratch after this tool)

Apply these checks on each sequence in `filtered_designs[].sequence`
before sending to AF2. The agent can compute all five in bash scratch
using BioPython (already a dep in the host venv):

```python
from Bio.SeqUtils.ProtParam import ProteinAnalysis
# 1. Unpaired cysteines (VHH has one canonical disulfide = 2 Cys)
n_cys = seq.count("C")
unpaired = n_cys - 2  # flag if > 0

# 2. N-glycosylation motifs in CDR regions (NxS/T, x != P)
import re
nglyc = re.findall(r'N[^P][ST]', cdr_seq)  # flag if non-empty

# 3. Deamidation hotspots (NG, NS)
deamid = re.findall(r'N[GS]', cdr_seq)

# 4. Isomerization hotspots (DG, DS)
isomer = re.findall(r'D[GS]', cdr_seq)

# 5. pI
pa = ProteinAnalysis(seq)
pi = pa.isoelectric_point()  # flag if < 6.0 or > 9.0
```

Log results in plan.md. Designs with >1 unpaired Cys or pI out of
range are deprioritised before AF2 runs.

---

## Specificity counter-selection (OPRD1 / OPRK1)

For MOR binders, run AF2-multimer on each final candidate against
OPRD1 (PDB: fetch via data.rcsb_search + data.pdb_fetch) and OPRK1
as well. A design is **specific** if its MOR complex pLDDT exceeds
its OPRD1 and OPRK1 complex pLDDT by ≥ 5 points. Log the delta in
plan.md and result.json under `specificity_delta_oprd1` and
`specificity_delta_oprk1`.

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| 0 filtered designs | Bad hotspot selection or hotspots on wrong face | Re-examine epitope; pick more hydrophobic anchors |
| rfdiffusion exits non-zero | Framework PDB not found or CUDA < 11.8 | Check Docker image build; verify CUDA version |
| rf2 pAE all > 10 | CDR3 too long / short for the pocket geometry | Adjust loop_lengths H3 range |
| RF2 RMSD all > 2Å | Hotspots force incompatible backbone geometry | Reduce hotspot count or move to peripheral residues |
| AF2 complex pLDDT < 70 on MOR | TM helix vacuum exposure | Score binder chain A only; see "Membrane protein" above |

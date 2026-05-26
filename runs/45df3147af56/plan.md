# plan.md — binder to ubiquitin (PDB 1UBQ)

**Run:** 45df3147af56 · **Date:** 2026-05-26 · **Mode:** VALIDATION (no GPU pipeline run)

## Round 1 — target resolution + hypothesis (deliberation only)

### Target resolved
- **PDB:** 1UBQ — ubiquitin, 1.8 Å crystal structure (Vijay-Kumar et al. 1987), the canonical reference structure.
- **Chain:** A. Reported as "134 residues, 1-134, contiguous, no gaps" — **but only residues 1-76 are protein**
  (last ATOM = GLY A 76; 602 protein atoms). Residues 77-134 are **58 ordered waters** (HETATM), counted by the
  tool as chain residues. See learned note below.
- **Crop:** `A/1-76` → 602 atoms, 76 residues, contiguous, no gaps.
  Path: `/home/ubuntu/.proteinclaw/gpu-workspace/45df3147af56/pdb_fetch_0/1UBQ_chainA_crop1-76.pdb`
- **UniProt:** P0CG48 (Polyubiquitin-C, *Homo sapiens*, 685 aa = 9 head-to-tail ubiquitin repeats). Mature
  ubiquitin = the first 76-aa β-grasp domain. Sequence (1-76):
  `MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG`

### Research (kept brief per validation instructions)
- Ubiquitin's near-universal protein-recognition surface is the **Ile44 hydrophobic patch** — L8, I44, V70
  (+ H68), the surface engaged by essentially all ubiquitin-binding domains (UBA, UIM, CUE, etc.). This is
  textbook structural biology, so no scout fan-out / debate was run for the validation pass.

### Structural sandbox (biopython Shrake-Rupley SASA on the 1-76 crop)
- PHE4 56.8 · **LEU8 137.8** · ARG42 89.8 · **ILE44 29.0** · **HIS68 89.5** · **VAL70 37.4** (Å²).
- I44 is partly buried (it is the hydrophobic core of the patch), flanked by well-exposed L8/H68/V70 →
  a real, dockable hydrophobic groove. Confirms the Ile44 patch as the binder target.

### Design hypothesis (NOT executed — validation run)
- **Hotspots:** `A8,A44,A70` (canonical Ile44 patch; add A68 if under-constrained).
- **Binder length:** 55-75 aa mini-binder — ubiquitin is small (76 aa) and its functional epitope is a
  compact patch, so a short β/αβ binder covering the groove is appropriate; avoid >100 aa (would over-wrap a
  small target).
- **Would-be funnel:** RFD3 ~40-60 backbones → MPNN ~8 seq/backbone @ temp 0.1 → ESMFold pLDDT≥70 cut →
  AF2-multimer rank by binder-chain pLDDT. **Not run** — GPU pipeline deliberately skipped.

### Status
Validation objectives met: target resolved, plan recorded, one durable learned note promoted to the skills
(see Self-evolution announcement). Pipeline (RFD3/MPNN/ESM/AF2) intentionally **not** invoked.

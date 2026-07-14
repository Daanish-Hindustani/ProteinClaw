# ProteinClaw μOR nanobody campaign handoff

Date: 2026-07-14 UTC

## Objective

Build an agentic, long-running ProteinClaw workflow that proposes a **small,
high-confidence** set of nanobody candidates for difficult GPCRs, using human
μ-opioid receptor (μOR/MOR, UniProt P35372) as the first campaign. The workflow
must research, debate, generate, falsify, pivot, and iterate rather than stop
after two or three failed runs. Computational candidates are not experimentally
validated binders.

Active campaign/run ID: `mor_nanobody_campaign_v2`

Run artifacts: `runs/mor_nanobody_campaign_v2/`

GPU workspace on this VM:
`~/.proteinclaw/gpu-workspace/mor_nanobody_campaign_v2/`

The GPU workspace and Docker images may disappear when the VM is destroyed.
The repository changes and committed/copied run artifacts must therefore be
preserved separately before termination.

## Most important conclusions

1. The earlier target audit was wrong: PDB 5C1M and 8QOT are **mouse** MOR, not
   human MOR. They are useful homolog/reference complexes only. Human targets
   used in the corrected campaign are active DAMGO/Gi-bound 8EFQ and inactive
   9MQI.
2. Sequence-only AlphaFold-Multimer is not a valid fail-closed confirmation
   gate for this state-dependent target. It rejected exact experimentally
   validated Nb63 (ipTM 0.21, ipSAE 0), so it cannot establish state
   selectivity here.
3. Unconditioned/scaffold BoltzGen candidates often found the correct receptor
   face but produced clashing, low-confidence poses. Increasing batch size or
   relaxing thresholds was explicitly rejected in recorded debates.
4. State-conditioned Boltz-2 strongly separated exact Nb62 on active versus
   inactive human MOR, but its **untemplated binder pose was wrong**. Exact
   Nb63 failed the same pose QC. Therefore Boltz-2 scores are useful as an
   orthogonal sequence/state signal, not as the sole pose generator for this
   known VHH family.
5. The successful pivot was to preserve the solved Nb39 pose: sequence-align
   mouse 5C1M MOR to human 8EFQ, transfer the VHH pose, graft only published
   Nb62/Nb63 mutations, and perform backbone-restrained OpenMM relaxation.
   This produced the best current modeled complex and passed the geometry-only
   gate.

## Debate record

Yes, debates were run and recorded. See:

- `runs/mor_nanobody_campaign_v2/debate.jsonl`
- the appended “Native Debate Record” sections in
  `runs/mor_nanobody_campaign_v2/plan.md`

The important adjudications were:

- do not expand weak iid batches;
- do not relax hotspot, clash, CDR, or confidence thresholds to create a hit;
- retire the de novo Gi-mimetic recipe when its predeclared control tied/beat
  it;
- reject high Boltz-2 scores when exact positive-control poses fail geometry;
- pivot to solved-pose transfer plus restrained mutation refinement.

## Corrected human target representations

Active human MOR/Nb39-family target:

`~/.proteinclaw/gpu-workspace/mor_nanobody_campaign_v2/gpcr_target_prepare_21/target_manifest.json`

- source: PDB 8EFQ, human P35372, chain R
- state: active
- face: intracellular
- 12 mapped Nb39/Nb62/Nb63-family anchors
- intact resolved receptor chain, schema v3, verified topology and numbering

Inactive matched intracellular counterstate:

`~/.proteinclaw/gpu-workspace/mor_nanobody_campaign_v2/gpcr_target_prepare_57/target_manifest.json`

- source: PDB 9MQI, human P35372, chain A
- state: inactive
- face: intracellular
- same homologous author-numbered anchor set
- construct caveat: deposited state was stabilized by Nb6M/NabFab; those chains
  were removed from prediction

The original inactive extracellular/NbE target is step 23.

## Candidate and control results

### Failed BoltzGen exploration

- Step 31, active Nb39/Nb63 scaffold redesign, four candidates: all failed.
  Hotspot 25–33%, clashes 5.03–7.55, interface confidence 0.57–0.61.
- Step 32, inactive NbE scaffold redesign, four candidates: correct face and
  BSA, but clashes 9.43–12.08 and confidence/H3 0.47–0.56.
- Step 33, active Gi-mimetic de novo, four candidates: best candidate had 91%
  hotspots but clash 10.26 and interface confidence 0.50.
- The step-33 rank-1 candidate did not separate from its predeclared loop
  permutation control under Boltz-2: candidate ipTM 0.775/interface 0.863;
  control ipTM 0.842/interface 0.792. Branch retired.

### State-conditioned Boltz-2 calibration

Exact Nb63 positive, step 52:

- ipTM 0.947
- interface pLDDT 0.951

Composition-preserving CDR-scrambled Nb63, step 53:

- ipTM 0.672
- interface pLDDT 0.785

This established sequence sensitivity in a one-sample smoke test.

Exact Nb62 active, five samples, step 59:

- ipTM 0.951–0.954
- interface pLDDT 0.948–0.951

Exact Nb62 inactive counterstate, five samples, step 60:

- ipTM 0.603–0.721
- interface pLDDT 0.672–0.689

Every active sample exceeded every inactive sample. However, all five active
Boltz-2 poses failed geometry: only 25% intended hotspots and clashes 23–27.
Exact Nb63 showed the same failure (25% hotspots, clash 26.65). Do not promote
from these scores alone.

### Current best pose-preserved Nb62 model

Tool run: step 66

Modeled complex:

`~/.proteinclaw/gpu-workspace/mor_nanobody_campaign_v2/gpcr_pose_refine_66/refined_complex.pdb`

Inputs:

- human active MOR: prepared 8EFQ target from step 21
- solved reference pose: 5C1M chains A/B
- sequence alignment, not raw author-number equality
- Nb62 mutations: `T52S`, `S54D`, `D57F`, `T59E`, `V74A`, `A75Y`
- OpenMM 8.5.2, CUDA 12 plugin, A100
- backbone restraint: 1000 kJ/mol/nm²
- 1000 minimization iterations

Alignment/refinement results:

- 171 transmembrane Cα pairs
- receptor sequence identity: 98.59%
- transmembrane RMSD: 0.778 Å
- CUDA platform verified
- energy: 28,215,361 to −48,694 kJ/mol
- elapsed: 61 seconds

Reference-calibrated geometry QC, step 68:

- geometry-only gate: **pass**
- intended hotspot satisfaction: 50%
- mapped hotspots: 100%
- BSA: 2741.4 Å²; solved 5C1M reference: 2365.2 Å²
- clash score: 2.19; solved reference: 2.15
- forbidden-face contacts: 0
- CDR contact fraction: 0.571; solved reference: 0.583
- reference-calibrated CDR minimum: 0.533
- strict confidence gate: not passed, by design, because OpenMM has no pLDDT

This is the strongest current computational finalist, but it is an
experimentally grounded/homolog-transferred Nb62 model, not a new experimentally
validated binder and not yet a novel AI-designed sequence.

## Exact known-positive sequences

The runtime file is:

`~/.proteinclaw/gpu-workspace/mor_nanobody_campaign_v2/known_positive_inputs.json`

It contains exact Nb39, Nb62, Nb63, and NbE inputs. Nb63 is Nb39 plus
`T52S,S54D,D57F,T59E`; Nb62 additionally contains `V74A,A75Y`. These mutation
numbers are PDB/paper author numbers, not simple sequence indices.

Primary evidence recorded in `research.jsonl` includes:

- human active MOR 8EFQ: https://www.rcsb.org/structure/8EFQ
- human inactive MOR 9MQI: https://www.rcsb.org/structure/9MQI
- mouse active MOR/Nb39 5C1M: https://www.rcsb.org/structure/5C1M
- mouse extracellular MOR/NbE 8QOT: https://www.rcsb.org/structure/8QOT
- Nb62/Nb63 engineering study:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12871209/
- NbE study: https://pmc.ncbi.nlm.nih.gov/articles/PMC11464722/

## Repository changes

Major new/updated components include:

- `src/proteinclaw/tools/gpcr_target.py`
  - schema-v3 state-specific target manifests
  - evidence-grounded hypothesis portfolio
  - verified author/label numbering and topology
- `src/proteinclaw/tools/gpcr_candidate_qc.py`
  - fail-closed GPCR QC
  - fixed glycine/Atom truthiness bug in `analysis.py`
  - prediction-sequence, manifest-label, and manifest-author numbering modes
  - reference-calibrated BSA, clashes, and CDR-contact fraction
  - geometry-only policy for force-field models; never claims strict confidence
- `src/proteinclaw/tools/boltz2_gpcr/`
  - state-conditioned Boltz-2 2.2.1
  - verified receptor template, soft epitope pocket, physical potentials
  - correct output parsing and CUDA/Triton compiler setup
- `src/proteinclaw/tools/gpcr_pose_refine/`
  - solved-pose homolog transfer
  - sequence-aligned receptor correspondence
  - fail-closed RMSD ceiling
  - exact mutation/sequence verification
  - OpenMM 8.5.2 plus `openmm-cuda-12==8.5.2`
  - explicit CUDA plugin directory; no silent CPU fallback
- `src/proteinclaw/tools/boltzgen_nanobody/`
  - bounded BoltzGen scaffold redesign support
- updated workflow/nanobody/tool/learned skills under `skills/`
- updated `README.md`, `docs/ARCHITECTURE.md`,
  `docs/mcp-tool-surface.md`, and `docs/gpcr-campaign-improvements.md`

The worktree is intentionally dirty. Do not reset or discard unrelated/user
changes. Run `git status --short` before continuing.

## Docker images used on this VM

These need rebuilding after a VM reset:

- `proteinclaw/boltz2-gpcr:2.2.1`
- `proteinclaw/gpcr-pose-refine:openmm-8.5.2`
- the existing BoltzGen/AF-M images used by ProteinClaw

The pose-refine image must expose all three OpenMM platforms:

```bash
docker run --rm --gpus all \
  --entrypoint python3 \
  proteinclaw/gpcr-pose-refine:openmm-8.5.2 \
  -c 'from openmm import Platform; print([Platform.getPlatform(i).getName() for i in range(Platform.getNumPlatforms())])'
```

Expected: `['Reference', 'CPU', 'CUDA']`.

The Dockerfile sets:

`OPENMM_PLUGIN_DIR=/usr/local/lib/python3.12/dist-packages/OpenMM.libs/lib/plugins`

Without that setting the CUDA wheel is installed but not discovered.

## Validation already run

Earlier, before the most recent pose-refinement additions:

- full non-GPU tests: 342 passed, 2 skipped, 12 deselected
- Ruff passed
- plugin validator passed
- packaging/skill tests passed

After the recent additions, targeted tests passed:

- `tests/tools/test_boltz2_gpcr.py`
- `tests/tools/test_gpcr_candidate_qc.py`
- `tests/tools/test_gpcr_pose_refine.py`
- targeted Ruff checks
- the new pose-refine skill passed `quick_validate.py`

The **full gates have not yet been rerun after the final pose-refinement/QC
changes**. That is the first engineering task on resume.

## Resume procedure on a fresh VM

1. Read `AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md`,
   `docs/mcp-tool-surface.md`, `docs/agent-platform-install.md`,
   `docs/gpu-docker-setup.md`, `docs/repository-tree.md`, and this file.
2. Install/verify NVIDIA driver, `nvidia-smi`, Docker Engine, and NVIDIA
   Container Toolkit using `docs/gpu-docker-setup.md`.
3. Verify GPU-in-container access:

   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
   ```

4. Rebuild required images from their tool directories. Do not rely on the
   ad-hoc overlay layers used during live debugging; the checked-in Dockerfiles
   contain the final requirements.
5. Restore/copy the campaign GPU workspace if available. If unavailable,
   recreate the target manifests and reference files from the recorded inputs
   in `trace.jsonl`/`plan.md`; do not reuse the old mouse-as-human assumption.
6. Run full validation:

   ```bash
   uv run --extra dev ruff check .
   uv run --extra dev pytest -m "not gpu and not live"
   uv run --extra dev pytest tests/test_agent_platform_packaging.py tests/agent/test_skill_invariants.py tests/agent/test_skills.py
   uv run python .github/scripts/validate_codex_plugin.py .
   ```

7. Resume the run through `proteinclaw_run_resume`/`RunManager.resume_run` and
   keep recording research and debate with `proteinclaw_research_record` and
   `proteinclaw_debate_record`.

## Next scientific/engineering tasks

1. Add a final state-conditioned confirmation gate that combines:
   - pose-refinement geometry pass;
   - five active-state Boltz-2 samples;
   - five matched inactive-counterstate samples;
   - known-positive/control calibration;
   - complete distribution separation, not best-sample comparison.
   The previous turn was interrupted just before implementing this gate.
2. Update the relevant skills/docs to describe `confidence_policy` and
   reference-calibrated CDR contact handling explicitly.
3. Rerun Nb63 through `structure.gpcr_pose_refine` as a second family member and
   compare its refined geometry to Nb62. Keep the shortlist at two until a
   genuinely new variant earns promotion.
4. If designing novel variants, make only a tiny, evidence-derived set around
   Nb62/Nb63 (for example, carefully adjudicated intermediates at the published
   FR3 positions). Predeclare controls and falsification criteria before
   scoring. Do not launch another broad de novo batch.
5. Add developability/liability checks and a small opioid-receptor off-target
   panel before recommending wet-lab testing.
6. Generate/finalize the campaign report only after the combined confirmation
   gate exists. Report Nb62/Nb63 as published positive controls/family members,
   not discoveries by this campaign.

## Current honest status

The workflow and target representation are substantially better, the debate
loop is active and documented, and the campaign has one physically plausible,
reference-calibrated human active-MOR/Nb62 model. No novel nanobody sequence has
yet passed a complete final computational confirmation gate. No output from
this campaign should be described as experimentally validated binding,
affinity, specificity, or efficacy.

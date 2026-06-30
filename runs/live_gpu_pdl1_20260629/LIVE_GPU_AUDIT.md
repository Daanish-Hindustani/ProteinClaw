# Live GPU Test Audit — PD-L1 / Ubiquitin Tool Chain

Date: 2026-06-29

This was a real GPU/live validation, not a smoke test. It built and ran the
scientific containers on the local A100 through the ProteinClaw Python/router
tool path used by MCP domain tools.

## Host

- GPU: NVIDIA A100-SXM4-40GB
- Driver: 595.71.05
- Docker NVIDIA runtime: present
- Built images:
  - `proteinclaw/rfdiffusion3:0.1.0` — 10.9GB
  - `proteinclaw/proteinmpnn:0.1.0` — 14.2GB
  - `proteinclaw/esmfold:0.1.0` — 14.1GB
  - `proteinclaw/af2multimer:0.1.0` — 15.8GB

## Live Commands Run

- `uv run --extra dev pytest -m gpu tests/tools/rfdiffusion3/test_e2e_gpu.py -s`
  - Result: passed
  - Runtime: 171.73s
  - Target: PD-L1 IgV crop, PDB `5JDS`, chain A, residues 18-134
  - Output: 2 RFdiffusion3 backbone complexes
  - Peak VRAM: 4501MB
  - Artifacts:
    - `/home/ubuntu/.proteinclaw/gpu-workspace/rfd3-test-d53ac6fa/output.json`
    - `/home/ubuntu/.proteinclaw/gpu-workspace/rfd3-test-d53ac6fa/rfdiffusion3_0/inputs_binder_0_model_0.pdb`
    - `/home/ubuntu/.proteinclaw/gpu-workspace/rfd3-test-d53ac6fa/rfdiffusion3_0/inputs_binder_0_model_1.pdb`

- `uv run --extra dev pytest -m gpu tests/tools/proteinmpnn/test_e2e_gpu.py -s`
  - Result: passed
  - Runtime: 375.23s
  - Output: 4 designed sequences
  - Average score: 0.914
  - Peak VRAM: 613MB
  - Artifact: `/home/ubuntu/.proteinclaw/gpu-workspace/mpnn-test-6816e2f1/output.json`

- `uv run --extra dev pytest -m gpu tests/tools/esmfold/test_e2e_gpu.py -s`
  - Result: passed
  - Runtime: 400.32s
  - Output: 3 folded monomer structures
  - Mean pLDDT: 67.0
  - Ubiquitin pLDDT: 77.36
  - Peak VRAM: 14203MB
  - Artifact: `/home/ubuntu/.proteinclaw/gpu-workspace/esm-test-345d0263/output.json`

- `uv run --extra dev pytest -m gpu tests/tools/alphafold2_multimer/test_e2e_gpu.py -s`
  - Result: passed
  - Runtime: 553.03s
  - Output: AF2-multimer complex PDB
  - Complex confidence: 45.37
  - ipSAE: 0.000
  - ipTM: 0.09
  - Peak VRAM: 2651MB
  - Artifact: `/home/ubuntu/.proteinclaw/gpu-workspace/af2-test-4b9f23cd/output.json`

- `analysis.interface_metrics` on the AF2 complex PDB
  - Result: passed
  - Interface contacts: 52
  - Interface BSA: 1399.9 Å²
  - Clash score: 342.76 per 1k atoms
  - Artifact: `/home/ubuntu/ProteinClaw/runs/live_gpu_pdl1_20260629/interface_metrics_af2_dummy.json`

## Workflow/Skill Evaluation

The live tool order matches the `proteinclaw-minibinder` and per-tool skills:

1. Target structure was fetched and cropped before design.
2. RFdiffusion3 generated binder backbones against the target.
3. ProteinMPNN generated sequences for a real backbone.
4. ESMFold validated monomer folding behavior.
5. AF2-multimer generated a complex and exposed interface-ranking metrics.
6. Interface metrics computed deterministic contact/BSA/clash QC on an AF2
   complex PDB.

The run also matches the plugin/MCP architecture split:

- ProteinClaw owns scientific wrappers, GPU Docker execution, artifacts, and
  reportable envelopes.
- External agents own research, debate, subagents, hypothesis selection, and
  iteration planning.

## Important Limitation

This validates that the live GPU scientific tools run correctly end-to-end on
this host. It is not a production binder discovery campaign because the tests
use minimal counts and wrapper sanity targets. A production run should use the
same tool chain with larger round budgets, real per-round research/debate, AF2
ranking of actual RFdiffusion3+ProteinMPNN candidates, deterministic interface
metrics, and round-to-round refinement.

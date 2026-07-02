# GPU And Docker Setup

ProteinClaw can run packaging tests without a GPU. Full minibinder and nanobody
campaigns require GPU-backed tools for RFdiffusion3, ProteinMPNN, ESMFold, and
AlphaFold2-multimer.

## Requirements

- Linux host or a supported GPU workstation environment.
- NVIDIA driver compatible with the CUDA images used by the tool containers.
- Docker Engine.
- NVIDIA Container Toolkit.
- Enough VRAM for the selected workflow. AF2-multimer is usually the limiting
  stage.

## Verify Docker GPU Access

Run:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

The command should print the GPU model, driver, CUDA compatibility, and memory.
If it cannot see the GPU, fix Docker/NVIDIA runtime before debugging
ProteinClaw.

## Runtime Path Model

ProteinClaw tools pass file paths between stages. GPU tools may run in Docker,
so host paths are translated into the mounted workspace used by containers.

Important rules:

- Trust returned paths. Pass tool output paths directly into the next tool.
- Keep generated artifacts under the ProteinClaw run directory.
- Do not paste PDB contents through the model context.
- Set `PROTEINCLAW_WORKSPACE_ROOT` when the default workspace inference does not
  match the host path mounted into containers.

Example:

```bash
export PROTEINCLAW_RUNS_DIR="$HOME/.proteinclaw/runs"
export PROTEINCLAW_WORKSPACE_ROOT="$HOME/.proteinclaw"
```

## Compute Budget Expectations

Approximate relative cost:

- RCSB/UniProt/PDB fetch and analysis: cheap CPU/network.
- RFdiffusion3: GPU, minutes per backbone.
- ProteinMPNN: cheap relative to AF2, but still part of the GPU/container path.
- ESMFold: GPU, batchable, useful as a pre-filter.
- AF2-multimer: expensive GPU stage and usually the bottleneck.
- Interface metrics and AF-M screen scoring: CPU/in-process after AF2 outputs
  exist.

Agents should size funnels explicitly. A plan such as 12 backbones x 8 sequences
means up to 96 AF2 jobs before confirmation. That can become an overnight run
on a single workstation.

## OOM And Failure Handling

When a GPU tool returns a structured OOM or container error:

1. Record the failure in `plan.md`.
2. Retry at most once with an adjusted parameter:
   - smaller target crop,
   - fewer candidates,
   - fewer AF2 models,
   - lower recycle count,
   - smaller ESMFold batch.
3. If the adjusted call fails, drop that branch or stop with
   `needs_human_review`.

Do not enter retry loops. Do not silently switch to a scientifically different
workflow without recording the change.

## Tests

Default non-GPU tests:

```bash
uv run --extra dev pytest -m "not gpu and not live"
```

GPU/live tests are intentionally separate. Run them only on a configured host
with expected data/model/container availability.


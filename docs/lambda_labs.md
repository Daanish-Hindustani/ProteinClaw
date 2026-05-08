# ProteinClaw on Lambda Labs

End-to-end guide for spinning up a Lambda Labs GPU instance, installing the real protein-design tools, and validating each piece by hand before turning the orchestrator loose on real workloads.

## 1. Prerequisites

- A [Lambda Labs](https://lambdalabs.com/service/gpu-cloud) account with billing set up.
- An SSH key uploaded under **Account → SSH keys**.
- A persistent filesystem attached to the region you'll launch in (recommended — model weights survive instance shutdown that way).

## 2. Pick an instance

The pipeline's heaviest step is RFdiffusion. Pick a GPU with ≥ 24 GB VRAM. Recommendations:

| Instance | GPU | When to use |
|---|---|---|
| `gpu_1x_a10` | A10 (24 GB) | Smallest viable; OK for binders ≤ 120 aa |
| `gpu_1x_a100_pcie_40gb` | A100 (40 GB) | Good default for development |
| `gpu_1x_h100_pcie` | H100 (80 GB) | Faster + more headroom |
| `gpu_2x_a100_sxm4` and up | multi-A100 | Only if you fan out many parallel branches |

**Cost note**: A100 PCIe is ~$1.30/hr; H100 ~$2.50/hr. The first run includes a one-time ~30 min install + ~10 GB weight download — that's ~$0.65 sunk cost on A100 before the first design runs. Use `lambda_labs_setup.sh --check` after first run to confirm idempotency for restarts.

## 3. Launch + connect

From the Lambda console:

1. Launch the chosen instance (Ubuntu 22.04 with the **Lambda Stack** preinstalled — that's NVIDIA driver + CUDA + cuDNN ready to go).
2. Mount your persistent filesystem at `/home/ubuntu/persistent` (or whatever path you prefer).
3. SSH in:
   ```bash
   ssh ubuntu@<instance-ip>
   ```

Quick sanity check before doing anything else:

```bash
nvidia-smi
```

You should see your GPU and the driver version. If `nvidia-smi` is missing the Lambda Stack didn't install correctly — file a support ticket; don't try to install drivers yourself.

## 4. Clone and run setup

```bash
# Clone wherever you like; I recommend the persistent volume so weights survive shutdown
cd ~/persistent
git clone <your-proteinclaw-repo-url> proteinclaw
cd proteinclaw

# Install everything (~30-60 min the first time, mostly the RFdiffusion weight download)
./scripts/lambda_labs_setup.sh
```

Useful flags:

```bash
./scripts/lambda_labs_setup.sh --check               # report what's already installed, install nothing
./scripts/lambda_labs_setup.sh --skip-protein-mpnn   # if you only need RFdiffusion
./scripts/lambda_labs_setup.sh --with-colabfold      # add full AlphaFold via ColabFold
```

After it finishes:

```bash
echo 'source ~/.proteinclaw_env' >> ~/.bashrc
source ~/.proteinclaw_env
```

## 5. What the setup script actually did

1. Installed apt build deps + git-lfs.
2. Installed Miniforge (mamba) at `~/proteinclaw-tools/miniforge3` — isolated from the system Python.
3. Installed `uv` (the Python package manager ProteinClaw uses).
4. Ran `uv sync --extra dev` in the repo root → ProteinClaw + dev deps in `.venv`.
5. Created the conda env `proteinclaw-rfdiffusion3` from `envs/rfdiffusion3.yml`, cloned RFdiffusion to `~/proteinclaw-tools/RFdiffusion`, downloaded all 8 model checkpoints (~10 GB) to `models/`.
6. Same for ProteinMPNN at `~/proteinclaw-tools/ProteinMPNN`.
7. Optionally created the ColabFold env.
8. Wrote `~/.proteinclaw_env` exporting `PROTEINCLAW_BACKEND=auto`, `RFDIFFUSION_PATH`, `PROTEINMPNN_PATH`, plus the two `*_PYTHON` env vars that point ProteinClaw at the right conda interpreter.

## 6. Manual tests (in increasing complexity)

There's a guided runner — `scripts/smoke_test.sh` — that walks you through the same tests interactively (`enter` to run a step, `s` to skip, `q` to quit). Or run them by hand from this doc.

### 6.1 GPU + driver

```bash
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
```

**Proves**: the Lambda Stack exposed the GPU. If this is missing, nothing else will work.

### 6.2 PyTorch sees CUDA inside the RFdiffusion env

```bash
$PROTEINCLAW_RFDIFFUSION_PYTHON -c \
  "import torch; print('cuda', torch.cuda.is_available(), 'devices', torch.cuda.device_count())"
```

**Proves**: PyTorch was installed against a CUDA build that matches your driver. If this prints `cuda False`, the conda env's pytorch-cuda version doesn't match the driver — re-create the env after editing `envs/rfdiffusion3.yml` to point at a matching CUDA.

### 6.3 RCSB REST is reachable

```bash
curl -fsS https://data.rcsb.org/rest/v1/core/polymer_entity/1ABC/1 | head -50
```

**Proves**: the public RCSB Data API works from your instance. ProteinClaw's RCSB tool wraps exactly this endpoint.

### 6.4 ESM Atlas folding API is reachable

```bash
curl -fsS -X POST \
  --data 'MGSSHHHHHHSSGLVPRGSHMRGPNPTAASLEASAGPFTVRSFTVSRPSGYGAGTVYYPTNAGGTV' \
  https://api.esmatlas.com/foldSequence/v1/pdb/ | head -5
```

**Proves**: ESM Atlas accepts your sequence and returns a PDB. ProteinClaw's AlphaFold tool defaults to this endpoint when `COLABFOLD_BIN` isn't set.

### 6.5 Foldseek public server accepts tickets

```bash
echo 'HEADER fake' > /tmp/q.pdb
curl -fsS -F 'q=@/tmp/q.pdb' \
          -F 'database[]=pdb100' \
          -F 'mode=3diaa' \
          https://search.foldseek.com/api/ticket
```

**Proves**: Foldseek's submit endpoint is reachable. The full search is ticket + poll + result; our wrapper does all three.

### 6.6 RFdiffusion direct CLI

This is the load-bearing manual test for GPU work — if RFdiffusion runs end-to-end here, the conda env, weights, and GPU are all good.

```bash
mkdir -p /tmp/rfdiff_smoke
$PROTEINCLAW_RFDIFFUSION_PYTHON \
    $RFDIFFUSION_PATH/scripts/run_inference.py \
    inference.output_prefix=/tmp/rfdiff_smoke/test \
    'contigmap.contigs=[100-100]' \
    inference.num_designs=1 \
    denoiser.noise_scale_ca=0 \
    denoiser.noise_scale_frame=0
ls -la /tmp/rfdiff_smoke/
```

**Proves**: weights load, GPU does forward passes, output PDB lands on disk. Expected runtime ~30-90 s on A100.

### 6.7 ProteinMPNN direct CLI

```bash
BACKBONE=$(ls /tmp/rfdiff_smoke/test_*.pdb | head -1)
mkdir -p /tmp/mpnn_smoke
$PROTEINCLAW_PROTEIN_MPNN_PYTHON \
    $PROTEINMPNN_PATH/protein_mpnn_run.py \
    --pdb_path "$BACKBONE" \
    --out_folder /tmp/mpnn_smoke \
    --num_seq_per_target 2 \
    --sampling_temp 0.1 \
    --batch_size 1
cat /tmp/mpnn_smoke/seqs/*.fa
```

**Proves**: ProteinMPNN can read a real backbone (the one RFdiffusion just produced) and write designed sequences. Useful to debug when the integrated pipeline hangs — if this works in isolation but the integrated run doesn't, it's a ProteinClaw plumbing issue.

### 6.8 ProteinClaw with mocked tools (sanity)

```bash
PROTEINCLAW_BACKEND=mock uv run pytest tests/orchestrator/test_orchestrator_integration.py -v
```

**Proves**: the orchestrator + pipeline + planner + evaluator are wired correctly on this box. Nothing GPU-related here — failure means a build-system or import problem, not a GPU one.

### 6.9 ProteinClaw with real backends — the real test

```bash
uv run pytest -m expensive -v
```

**Proves**: end-to-end run with the orchestrator dispatching real RCSB / RFdiffusion / ProteinMPNN / AlphaFold / Foldseek calls. Expected runtime: 5-15 min on A100 depending on which expensive tests you've added.

If 6.6 + 6.7 pass but 6.9 fails, the failure is in ProteinClaw's wrapper layer (argument construction, output parsing, env-var routing). Read the `ToolExecutionError` message — it carries `stderr` from the failing subprocess.

## 7. Common issues

**`PROTEINCLAW_RFDIFFUSION_PYTHON` is empty after sourcing the env file**
The setup script only writes that var when it found the conda env. Re-run `./scripts/lambda_labs_setup.sh --check`; if it reports the env missing, re-run without `--check`.

**`torch.cuda.is_available()` returns False**
The pytorch-cuda version in `envs/rfdiffusion3.yml` doesn't match your driver. Look up the correct cudatoolkit version (`nvidia-smi` shows the driver-supported CUDA) and edit the YAML, then `mamba env remove -n proteinclaw-rfdiffusion3 && ./scripts/lambda_labs_setup.sh`.

**RFdiffusion crashes with `OutOfMemoryError`**
You're on a 24 GB GPU and the design is too large. Either bump to a larger instance or shorten the binder length in your contigs.

**`ToolExecutionError: foldseek polling timed out`**
The Foldseek public server is rate-limited; jobs queue. Either retry or install Foldseek locally (out of scope for this doc).

**Setup script complains about `git lfs install`**
`git lfs` was missing — re-running after a fresh `apt install git-lfs` should work. The script tries to install it, but apt sometimes flakes on a fresh instance.

## 8. Tear down (don't forget)

Lambda bills by the hour. When you're done:

```bash
# (optional) save anything you wrote on ephemeral disk back to persistent storage
mv /tmp/rfdiff_smoke ~/persistent/

# from the Lambda console:
# 1. Stop the instance (you'll keep the persistent volume)
# OR 2. Terminate it (release everything)
```

For the next session, `git pull` in `~/persistent/proteinclaw` and re-run `./scripts/lambda_labs_setup.sh` — it's idempotent and will skip any work already on the persistent volume.

# Protein Design Plugin

This plugin adds a `protein_design` toolset for target discovery, literature
search, RFD3 backbone generation, ProteinMPNN sequence design, and ESMFold
validation.

## What ships

| Tool | Purpose | Runtime |
|---|---|---|
| `pubmed_search` | PubMed literature search with automatic query variation | HTTPS API |
| `uniprot_search` | UniProtKB target sequence and annotation lookup | HTTPS API |
| `rcsb_search` | RCSB PDB structure search, optional PDB/CIF download, chain/range metadata | HTTPS API |
| `inspect_structure` | Local PDB/CIF inspection for chains, gaps, HETATM records, and resolution | Local Python |
| `rfd3_design` | RFdiffusion3 backbone/design generation | Docker + Foundry |
| `protein_mpnn_design` | ProteinMPNN/LigandMPNN sequence design | Docker + Foundry |
| `esmfold_predict` | ESMFold structure prediction and foldability triage | Docker + local ESMFold image |
| `alphafold2_multimer_predict` | AlphaFold2/ColabFold multimer complex prediction | Docker + configured AF2/ColabFold image |

Each tool has a matching skill under `skills/protein-design/`. The skills teach
the agent when to use the tool and how to interpret results. The RFD3 skill is
especially important because it contains the contig-construction workflow.
There is also a workflow skill, `protein-binder-design`, that teaches the agent
how to combine the independent tools for binder-design tasks without hardwiring
the tools into a mandatory pipeline.

## Requirements

Minimum:

- ProteinClaw running from this checkout or an install that includes this plugin.
- Internet access for PubMed, UniProt, and RCSB.
- Docker for RFD3, ProteinMPNN, and ESMFold.

For local model execution:

- Linux host with NVIDIA GPU.
- NVIDIA driver installed on the host.
- NVIDIA Container Toolkit installed so `docker run --gpus all ...` works.
- Enough disk for Docker images and model weights. The Foundry image with
  weights is large; expect many GB.

Quick GPU check:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If that fails, fix Docker/GPU access before debugging ProteinClaw.

## Lambda Cloud setup

This section is for Lambda Cloud / Lambda Labs GPU VMs, not AWS Lambda. The
protein-design models need a normal Linux GPU host with Docker.

On a fresh Lambda Cloud instance:

```bash
ssh ubuntu@<lambda-instance-ip>
git clone <your-hermes-agent-repo-url> hermes-agent
cd hermes-agent
scripts/setup_protein_design_lambda.sh
```

The setup script:

- Installs base Ubuntu packages needed by ProteinClaw and Docker.
- Checks host `nvidia-smi` before Docker setup and installs the recommended
  Ubuntu NVIDIA compute driver when it is missing or cannot communicate with
  the driver.
- Installs Docker if it is missing.
- Installs and configures NVIDIA Container Toolkit for `docker run --gpus all`.
- Runs `./setup-hermes.sh` to create the repo-local ProteinClaw virtualenv.
- Enables the `protein-design` plugin in `~/.hermes/config.yaml`.
- Writes default `protein_design` image/workspace config.
- Pulls the Foundry image used by RFD3 and ProteinMPNN.
- Builds the local ESMFold Docker image.
- Pulls the configured AlphaFold2/ColabFold image used by AF2 multimer
  complex prediction.
- Runs GPU and command smoke tests.

Useful script options:

```bash
scripts/setup_protein_design_lambda.sh --skip-esmfold-build
scripts/setup_protein_design_lambda.sh --skip-alphafold2
scripts/setup_protein_design_lambda.sh --skip-images
scripts/setup_protein_design_lambda.sh --skip-docker-setup
scripts/setup_protein_design_lambda.sh --skip-hermes-install
scripts/setup_protein_design_lambda.sh --install-nvidia-driver
```

Use `--skip-esmfold-build` or `--skip-alphafold2` when you only want
RFD3/ProteinMPNN first, because the ESMFold build and AF2/ColabFold image can
take a while. Use `--skip-docker-setup` only if you have already confirmed this succeeds:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If the NVIDIA driver is missing or `nvidia-smi` says it cannot communicate with
the NVIDIA driver, rerun the setup script with:

```bash
scripts/setup_protein_design_lambda.sh --install-nvidia-driver
sudo reboot
```

The Lambda script uses Ubuntu's recommended driver flow internally:

```bash
sudo apt update
sudo ubuntu-drivers devices
sudo ubuntu-drivers autoinstall
sudo reboot
```

After reboot, rerun the setup script so Docker GPU checks and model image smoke
tests can complete.

After the script finishes, open a fresh shell if it added your user to the
Docker group, then start ProteinClaw:

```bash
cd ~/hermes-agent
source venv/bin/activate
hermes
```

If you need API keys or model provider credentials, add them to
`~/.hermes/.env` before launching ProteinClaw. For PubMed throughput, set:

```bash
cat >> ~/.hermes/.env <<'EOF'
NCBI_TOOL_EMAIL=you@example.org
NCBI_API_KEY=optional_ncbi_key
EOF
```

Expected config after setup:

```yaml
plugins:
  enabled:
    - protein-design

protein_design:
  foundry_image: rosettacommons/foundry:latest
  esmfold_image: hermes-esmfold:latest
  workspace_root: ~/.hermes/protein-design
  default_timeout_seconds: 7200
```

Lambda smoke tests from ProteinClaw:

```text
Use pubmed_search to find recent review papers on RFdiffusion protein binder design.
```

```text
Use rfd3_design in free_generation mode with output_name "lambda_debug",
num_designs 1, contig "60-80", guide_scale 1.5, num_timesteps 25.
```

```text
Use esmfold_predict on this sequence with num_recycles=4: MKT...
```

For long design jobs, keep outputs in the configured protein-design workspace
or attach persistent storage before scaling `num_designs`.

## Enable the plugin

Enable the plugin:

```bash
hermes plugins enable protein-design
```

Then start a new ProteinClaw session so plugin discovery and tool schemas are rebuilt.

Check that the toolset is visible:

```bash
hermes tools
```

If you run ProteinClaw with explicit toolsets, include `protein_design`.

## Local compute setup from ProteinClaw

During `hermes setup` or `hermes setup tools`, enable the `Protein Design`
toolset. ProteinClaw will ask whether to set up local Docker compute:

- Choose `Local Docker compute` to pull Foundry for RFD3/ProteinMPNN and build
  the local ESMFold image.
- Choose `Search only / configure later` to use PubMed, UniProt, and RCSB now
  without downloading model images.

You can run the same local compute setup directly:

```bash
scripts/setup_protein_design_local.sh
```

Useful direct-run options:

```bash
scripts/setup_protein_design_local.sh --skip-esmfold-build
scripts/setup_protein_design_local.sh --skip-alphafold2
scripts/setup_protein_design_local.sh --skip-foundry
scripts/setup_protein_design_local.sh --skip-smoke-tests
scripts/setup_protein_design_local.sh --install-nvidia-driver
```

This script does not install ProteinClaw or Docker. It expects Docker to already be
installed. For practical RFD3, ProteinMPNN, and ESMFold runs, Docker should have
GPU access through NVIDIA Container Toolkit.

If the host NVIDIA driver is missing on Ubuntu, run:

```bash
scripts/setup_protein_design_local.sh --install-nvidia-driver
sudo reboot
```

After reboot:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
scripts/setup_protein_design_local.sh
```

If `nvidia-smi` is still reported as "command not found" after the driver
install, rerun:

```bash
scripts/setup_protein_design_local.sh --install-nvidia-driver
```

The script will install the matching `nvidia-utils-*` package that provides
`nvidia-smi`.

## Configure API-backed tools

`uniprot_search` and `rcsb_search` do not need API keys.

`pubmed_search` works without an NCBI key, but NCBI allows better throughput
when requests identify the tool/user. Add these if you have them:

```bash
cat >> ~/.hermes/.env <<'EOF'
NCBI_TOOL_EMAIL=you@example.org
NCBI_API_KEY=optional_ncbi_key
EOF
```

The tool also reads `HERMES_PROTEIN_NCBI_EMAIL` and
`HERMES_PROTEIN_NCBI_API_KEY` if those are easier in your environment.

## Install Foundry for RFD3 and ProteinMPNN

RFD3 and ProteinMPNN use the official Foundry image:

```bash
docker pull rosettacommons/foundry:latest
```

Smoke test the image:

```bash
docker run --rm --gpus all rosettacommons/foundry:latest foundry --help
docker run --rm --gpus all rosettacommons/foundry:latest rfd3 --help
docker run --rm --gpus all rosettacommons/foundry:latest mpnn --help
```

The plugin defaults to this image:

```yaml
protein_design:
  foundry_image: rosettacommons/foundry:latest
```

Use the `slim` Foundry image only if you know where your checkpoints are and
mount them yourself. The plugin's v1 Docker runner assumes the default image has
the expected Foundry commands and weights available.

## Build the ESMFold image

ESMFold uses a dedicated image because its dependency stack is separate. The
image uses the HuggingFace `facebook/esmfold_v1` implementation directly,
matching the ProteinClaw/celltype-agent container pattern, instead of the
fragile upstream `esm-fold` CLI/OpenFold build path.

```bash
docker build -t hermes-esmfold:latest -f plugins/protein-design/docker/esmfold.Dockerfile plugins/protein-design/docker
```

Smoke test:

```bash
docker run --rm --entrypoint python3 hermes-esmfold:latest \
  -c "import sys; sys.path.insert(0, '/opt'); import implementation; print('esmfold image ok')"
```

CPU-only ESMFold is possible through the `cpu_only` tool argument, but it is
slow. GPU is the expected path.

## Configure paths and images

Relevant config keys in `~/.hermes/config.yaml`:

```yaml
protein_design:
  foundry_image: rosettacommons/foundry:latest
  esmfold_image: hermes-esmfold:latest
  alphafold2_image: ghcr.io/sokrypton/colabfold:1.6.1-cuda12
  alphafold2_command: colabfold_batch
  workspace_root: ~/.hermes/protein-design
  default_timeout_seconds: 3600
```

Environment variable overrides are also supported:

```bash
export HERMES_PROTEIN_FOUNDRY_IMAGE=rosettacommons/foundry:latest
export HERMES_PROTEIN_ESMFOLD_IMAGE=hermes-esmfold:latest
export HERMES_PROTEIN_ALPHAFOLD2_IMAGE=ghcr.io/sokrypton/colabfold:1.6.1-cuda12
export HERMES_PROTEIN_ALPHAFOLD2_COMMAND=colabfold_batch
export HERMES_PROTEIN_WORKSPACE_ROOT="$HOME/.hermes/protein-design"
export HERMES_PROTEIN_DEFAULT_TIMEOUT_SECONDS=3600
```

`workspace_root` is where generated FASTA/spec/output files go when the tool
does not naturally run inside the current project directory.

The local setup script pulls `alphafold2_image` and smoke-tests
`alphafold2_command` unless `--skip-alphafold2` is used. Override those values
if your AF2/ColabFold image uses a different command or database layout.

## Binder campaign workflow

The tools are independent. ProteinClaw does not physically chain them together in
code. The agent chooses which tool to call next based on the active skill and
the user's task. Binder design should be run as an iterative campaign, not as a
single pass that declares a winner too early.

1. Literature:
   - Use `pubmed_search` to gather papers and design precedent.
2. Target sequence:
   - Use `uniprot_search` for canonical sequence, domains, features, and PDB refs.
3. Target structure:
   - Use `rcsb_search` to find/download a structure and identify chains/ligands.
   - If you already know the structure ID, pass `pdb_ids` directly instead of
     searching by text.
   - Set `download_format` to `pdb` when strict PDB columns are useful, or
     `cif` when preserving mmCIF metadata is preferable.
   - Use returned `chains` metadata to find residue ranges, continuous ranges,
     and gaps before writing contigs.
   - Use `inspect_structure` on local/generated files before contig building or
     ProteinMPNN chain selection.
4. Backbone generation:
   - Use `rfd3_design`.
   - For binders, derive contigs from the actual target structure, e.g.
     `70-110,/0,A1-240`.
   - Put hotspot residues in `hotspot_residues`, not inside the contig.
   - Start with a tiny debug run, then generate 8-32 candidates per real round.
5. Sequence design:
   - Use `protein_mpnn_design` on generated RFD3 structures.
   - Pass a directory or `structure_paths` list to process multiple backbones.
   - Sweep sequence temperature around the most promising backbones.
6. Fold validation:
   - Use `esmfold_predict` with `num_recycles=4` initially, then increase for
     borderline candidates.
7. Complex prediction:
   - Use `alphafold2_multimer_predict` on promising binder-target sequence
     pairs when an AlphaFold2/ColabFold multimer image is configured.
   - Start with a small candidate set because AF2/Multimer is expensive.
   - Treat AF2 complex predictions as computational triage, not measured
     affinity.
8. Rank and iterate:
   - Keep a candidate table with contig, hotspots, `guide_scale`,
     `num_timesteps`, MPNN temperature, fold confidence, complex prediction
     status, and decision.
   - Change one or two variables per round instead of rerunning identical jobs.
   - Keep top candidates from distinct settings so the agent preserves diversity.
   - Report the winner as the best computational candidate, not a validated
     binder.

Useful parameter moves:

- Misses intended epitope: revise `hotspot_residues` or target chain/range.
- Poor interface geometry: try a longer binder or modestly increase
  `guide_scale`.
- Low diversity: broaden binder length range or increase MPNN temperature.
- Low ESMFold confidence: try shorter/tighter backbones, lower MPNN
  temperature, or regenerate RFD3 backbones.
- Repeated failures: stop and explain the blocker rather than spending compute
  blindly.

ESMFold is foldability triage, not binding-affinity proof. AF2/Multimer complex
prediction is stronger interface triage, but docking, MD, orthogonal scoring,
or wet-lab validation are still needed before claiming a binder works.

`alphafold2_multimer_predict` expects a compatible external Docker image. The
default command shape is `colabfold_batch`; configure
`protein_design.alphafold2_image` and `protein_design.alphafold2_command` for
your local AF2/ColabFold setup.

## RFD3 contig setup

Before calling `rfd3_design`, the agent should inspect the target file or use
`rcsb_search` to confirm chain IDs and residue numbering. Paper numbering can
disagree with PDB/mmCIF numbering; use the structure file.

Examples:

```text
free_generation: 80-120
binder:          70-110,/0,A1-240
motif_scaffold:  30-50,A45-52,40-70
multi-chain:     70-110,/0,A1-140,/0,B3-95
```

Rules:

- Designed segments are bare lengths or ranges: `80`, `70-110`.
- Fixed target/motif residues include chain IDs: `A1-240`, `B45`.
- Chain breaks are explicit: `/0`.
- Hotspots are passed separately as `hotspot_residues`.
- The tool runs Foundry with `prevalidate_inputs=True`.

## Manual smoke tests from ProteinClaw

After enabling the plugin, ask ProteinClaw:

```text
Use pubmed_search to find recent review papers on RFdiffusion protein binder design.
```

Then:

```text
Use uniprot_search to find the reviewed human PD-L1 entry and include the sequence.
```

For local Docker:

```text
Use esmfold_predict on this sequence with num_recycles=4: MKT...
```

For RFD3, start with a tiny debug run before scaling `num_designs`:

```text
Use rfd3_design in free_generation mode with output_name "debug_free_gen",
num_designs 1, contig "60-80", guide_scale 1.5, num_timesteps 25.
```

## Troubleshooting

### Plugin tools do not appear

- Run `hermes plugins enable protein-design`.
- Start a new ProteinClaw session.
- If using explicit toolsets, include `protein_design`.

### Docker says no GPU

Run:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If that fails, install/fix NVIDIA Container Toolkit. ProteinClaw cannot repair a
broken Docker GPU runtime.

If Docker reports `libnvidia-ml.so.1: cannot open shared object file`, the host
NVIDIA driver library is missing or not visible. Fix `nvidia-smi` on the host
first, then restart Docker and retry the Docker GPU check.

### RFD3 fails before generating outputs

- Confirm the target file exists inside the mounted workspace.
- Confirm contig chain IDs and residue numbers match the file.
- Try `num_designs=1` and `num_timesteps=25` for a fast debug run.
- If using an existing `input_path`, validate the JSON/YAML against Foundry's
  RFD3 docs.

### ESMFold image fails to build

ESMFold uses the NVIDIA PyTorch base image plus HuggingFace `transformers`.
The setup script builds the image and pre-downloads `facebook/esmfold_v1`.
If the build fails, check Docker Hub/NVIDIA container registry access and disk
space first; the image and cached model are large.

### PubMed rate limits

Set `NCBI_TOOL_EMAIL` and `NCBI_API_KEY`. Keep `max_results` reasonable.

## Safety and interpretation

The plugin produces computational candidates. It does not prove binding,
catalysis, expression, stability, safety, or biological function. Treat outputs
as design hypotheses that need independent computational checks and wet-lab
validation.

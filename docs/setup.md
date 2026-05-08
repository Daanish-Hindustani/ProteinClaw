# Setup

## Quick start

```bash
uv sync --extra dev
```

That installs ProteinClaw + dev tooling. The Python sandbox and all stub
infrastructure work out of the box. Real protein-design tools require a
small amount of additional setup (below).

## Backend defaults

ProteinClaw runs in **`auto`** mode by default — it picks the best available real backend for each tool:

| Tool | `auto` resolves to | Setup needed |
|---|---|---|
| RCSB | REST (`data.rcsb.org`) | None |
| Foldseek | REST (`search.foldseek.com`) | None |
| AlphaFold | ColabFold local **if** `COLABFOLD_BIN` set, else ESM Atlas REST | None for ESM Atlas; conda env for ColabFold |
| RFdiffusion3 | local subprocess **iff** `RFDIFFUSION_PATH` set | **Required** — see below |
| ProteinMPNN | local subprocess **iff** `PROTEINMPNN_PATH` set | **Required** — see below |

If a tool that requires installation is missing its env var, factory construction raises a `ToolExecutionError` with the exact install commands. There is no silent downgrade.

### Tests run with mocks

The test suite (`uv run pytest`) sets `PROTEINCLAW_BACKEND=mock` via `tests/conftest.py`, so CI never hits external services and never requires the heavy installs.

### Override resolution

Resolution order (highest priority first):

1. **Per-tool env var** (e.g. `PROTEINCLAW_RCSB_BACKEND=mock`).
2. **Global env var** `PROTEINCLAW_BACKEND` (e.g. `mock` or `auto`).
3. **Built-in default**: `auto`.

<!-- AUTO-GENERATED:env-vars (source: src/proteinclaw/tools/factory.py + scripts/lambda_labs_setup.sh) -->

**Backend selection**

| Env var | Choices | Default |
|---|---|---|
| `PROTEINCLAW_BACKEND` | `auto`, `mock` | `auto` |
| `PROTEINCLAW_RCSB_BACKEND` | `auto`, `mock`, `rest` | inherit |
| `PROTEINCLAW_FOLDSEEK_BACKEND` | `auto`, `mock`, `rest` | inherit |
| `PROTEINCLAW_ALPHAFOLD_BACKEND` | `auto`, `mock`, `esm_atlas`, `colabfold` | inherit |
| `PROTEINCLAW_RFDIFFUSION_BACKEND` | `auto`, `mock`, `local` | inherit |
| `PROTEINCLAW_PROTEIN_MPNN_BACKEND` | `auto`, `mock`, `local` | inherit |

**Install paths (required when `auto` resolves to `local`)**

| Env var | Description |
|---|---|
| `RFDIFFUSION_PATH` | Filesystem root of the RFdiffusion clone. |
| `PROTEINMPNN_PATH` | Filesystem root of the ProteinMPNN clone. |
| `COLABFOLD_BIN` | Absolute path to `colabfold_batch`. When set, AlphaFold's `auto` resolves to `colabfold`; when unset, falls back to `esm_atlas` REST. |

**Conda Python interpreters (subprocess targeting)**

| Env var | Description |
|---|---|
| `PROTEINCLAW_RFDIFFUSION_PYTHON` | Python interpreter inside the `proteinclaw-rfdiffusion3` conda env. The factory passes this to `LocalRFDiffusionBackend` so the subprocess uses the right env, not ProteinClaw's `.venv`. |
| `PROTEINCLAW_PROTEIN_MPNN_PYTHON` | Same, for the ProteinMPNN conda env. |

**Setup-script knobs**

| Env var | Default | Description |
|---|---|---|
| `INSTALL_PREFIX` | `$HOME/proteinclaw-tools` | Where the setup script puts Miniforge + tool clones. |
| `PROTEINCLAW_DIR` | `$(pwd)` | Repo root the setup script reads. |
| `MINIFORGE_VERSION` | `25.3.0-3` | Pinned for reproducibility. |
| `UV_VERSION` | `0.5.13` | Pinned for reproducibility. |

<!-- /AUTO-GENERATED:env-vars -->

Force every tool to mock for fast local iteration:

```bash
export PROTEINCLAW_BACKEND=mock
```

Or mock just one tool while running the rest live:

```bash
export PROTEINCLAW_RFDIFFUSION_BACKEND=mock
```

## Run checks

```bash
uv run ruff check src tests
uv run mypy
uv run pytest                  # excludes @pytest.mark.expensive by default
uv run pytest -m expensive     # opt-in: real tools / live network
```

## Installing the local GPU tools

The reference integration patterns are drawn from [jasonkim8652/protein-design-mcp](https://github.com/jasonkim8652/protein-design-mcp). Each tool gets its own conda env to avoid PyTorch version conflicts.

### RFdiffusion3

```bash
mamba env create -f envs/rfdiffusion3.yml
mamba activate proteinclaw-rfdiffusion3
git clone https://github.com/RosettaCommons/RFdiffusion /opt/RFdiffusion3
export RFDIFFUSION_PATH=/opt/RFdiffusion3
```

### ProteinMPNN

```bash
mamba env create -f envs/protein_mpnn.yml
mamba activate proteinclaw-protein-mpnn
git clone https://github.com/dauparas/ProteinMPNN /opt/ProteinMPNN
export PROTEINMPNN_PATH=/opt/ProteinMPNN
```

### AlphaFold via ColabFold (optional, GPU)

```bash
mamba env create -f envs/colabfold.yml
mamba activate proteinclaw-colabfold
export COLABFOLD_BIN=$(which colabfold_batch)
```

Without `COLABFOLD_BIN`, AlphaFold falls back to the ESM Atlas REST API (no GPU; sequences ≤ 400 aa).

## Running expensive tests

Once a real backend is configured, opt-in tests exercise it end-to-end:

```bash
uv run pytest -m expensive
```

These are excluded from the default `pytest` invocation and from CI. Use them as a smoke test on the deployment box.

## Sandbox

The Python sandbox (`src/proteinclaw/sandbox/python_runner.py`) wraps untrusted analysis snippets in a subprocess with wall-clock + memory limits. Threat model is "LLM-written buggy script," not adversarial escape — see the module docstring.

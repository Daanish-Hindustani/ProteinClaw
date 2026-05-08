#!/usr/bin/env bash
#
# ProteinClaw — Lambda Labs GPU instance setup.
#
# Idempotent: re-running skips work that's already done. Targets a fresh
# Lambda Labs Ubuntu 22.04 instance where NVIDIA drivers + CUDA are
# already installed via the Lambda Stack. This script layers on:
#
#   - apt build deps + miniforge (mamba) + uv
#   - ProteinClaw repo + Python deps
#   - RFdiffusion conda env, repo, and model weights
#   - ProteinMPNN conda env and repo
#   - (optional) ColabFold conda env
#   - env vars exported to ~/.proteinclaw_env
#
# Env vars you can set to override defaults:
#   INSTALL_PREFIX   default $HOME/proteinclaw-tools
#   PROTEINCLAW_DIR  default $(pwd)
#   MINIFORGE_VERSION default Miniforge3-25.3.0-3
#   UV_VERSION       default 0.5.13

set -euo pipefail

# -- Help ----------------------------------------------------------------
HELP=$(cat <<'EOF'
ProteinClaw Lambda Labs setup

Usage:
  ./scripts/lambda_labs_setup.sh                      # default (RFdiff + MPNN, no ColabFold)
  ./scripts/lambda_labs_setup.sh --with-colabfold     # add ColabFold
  ./scripts/lambda_labs_setup.sh --skip-rfdiffusion   # skip RFdiffusion
  ./scripts/lambda_labs_setup.sh --skip-protein-mpnn  # skip ProteinMPNN
  ./scripts/lambda_labs_setup.sh --check              # report what's installed, install nothing
  ./scripts/lambda_labs_setup.sh -h | --help          # this message
EOF
)

# -- Pinned tool versions ------------------------------------------------
# Pinned for reproducibility. Bump these deliberately when you want a
# newer toolchain on the box; otherwise re-runs use exactly the same
# versions across instances.
MINIFORGE_VERSION="${MINIFORGE_VERSION:-25.3.0-3}"
UV_VERSION="${UV_VERSION:-0.5.13}"

# -- Colors --------------------------------------------------------------
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; NC=""
fi

log()  { printf '%s[setup]%s %s\n' "$BLUE" "$NC" "$*"; }
ok()   { printf '%s[ ok ]%s %s\n' "$GREEN" "$NC" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$YELLOW" "$NC" "$*"; }
err()  { printf '%s[fail]%s %s\n' "$RED" "$NC" "$*" >&2; }
step() { printf '\n%s%s== %s ==%s\n' "$BOLD" "$BLUE" "$*" "$NC"; }

# -- Args ----------------------------------------------------------------
INSTALL_RFDIFFUSION=1
INSTALL_PROTEIN_MPNN=1
INSTALL_COLABFOLD=0
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-rfdiffusion)   INSTALL_RFDIFFUSION=0 ;;
        --skip-protein-mpnn)  INSTALL_PROTEIN_MPNN=0 ;;
        --with-colabfold)     INSTALL_COLABFOLD=1 ;;
        --check)              CHECK_ONLY=1 ;;
        -h|--help)            printf '%s\n' "$HELP"; exit 0 ;;
        *)                    err "unknown arg: $1"; exit 2 ;;
    esac
    shift
done

# -- Paths ---------------------------------------------------------------
INSTALL_PREFIX="${INSTALL_PREFIX:-$HOME/proteinclaw-tools}"
PROTEINCLAW_DIR="${PROTEINCLAW_DIR:-$(pwd)}"
ENV_FILE="$HOME/.proteinclaw_env"

CONDA_ROOT="$INSTALL_PREFIX/miniforge3"
RFDIFFUSION_DIR="$INSTALL_PREFIX/RFdiffusion"
PROTEIN_MPNN_DIR="$INSTALL_PREFIX/ProteinMPNN"

mkdir -p "$INSTALL_PREFIX"

# Match conda env names exactly (anchored). Substring grep would treat
# `proteinclaw-rfdiffusion3-old` as already-existing and skip creation.
conda_env_exists() {
    local name="$1"
    "$CONDA_ROOT/bin/conda" env list 2>/dev/null \
        | awk '{print $1}' \
        | grep -qE "^${name}$"
}

# -- Phase: preflight ----------------------------------------------------
install_nvidia_driver() {
    # Bootstrap NVIDIA driver via Ubuntu's recommended path. Used when
    # `nvidia-smi` isn't on PATH (e.g. a non-Lambda-Stack image, or a
    # bare-metal Ubuntu install). The autoinstall step requires a reboot
    # before the driver becomes usable, so we exit non-zero with a clear
    # next-step message — re-running the script after reboot is idempotent.
    step "NVIDIA driver bootstrap"
    if [[ $CHECK_ONLY -eq 1 ]]; then
        warn "nvidia-smi missing (would auto-install in non-check mode)"
        return 1
    fi
    log "running: sudo apt-get update"
    sudo apt-get update -y
    log "running: sudo apt-get install -y ubuntu-drivers-common"
    sudo apt-get install -y --no-install-recommends ubuntu-drivers-common
    log "running: sudo ubuntu-drivers autoinstall"
    if ! sudo ubuntu-drivers autoinstall; then
        err "ubuntu-drivers autoinstall failed; check apt logs and rerun manually"
        exit 1
    fi
    printf '\n%sNVIDIA driver installed. A reboot is required.%s\n' "$BOLD$YELLOW" "$NC"
    printf '%sNext steps:%s\n' "$BOLD" "$NC"
    printf '  1. %ssudo reboot%s\n' "$GREEN" "$NC"
    printf '  2. After reconnect, re-run: %s./scripts/lambda_labs_setup.sh%s\n' "$GREEN" "$NC"
    exit 0
}

preflight() {
    step "Preflight"
    if [[ "$(uname -s)" != "Linux" ]]; then
        err "this script is for Linux Lambda Labs instances; you ran it on $(uname -s)"
        exit 1
    fi
    if ! command -v sudo >/dev/null; then
        err "sudo not found; this script needs sudo for apt and driver install"
        exit 1
    fi
    if command -v nvidia-smi >/dev/null; then
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
        ok "NVIDIA driver detected"
    else
        warn "nvidia-smi not on PATH — bootstrapping NVIDIA driver"
        install_nvidia_driver
    fi
    log "ProteinClaw repo:   $PROTEINCLAW_DIR"
    log "Tool install root:  $INSTALL_PREFIX"
    log "Env file:           $ENV_FILE"
    log "Miniforge version:  $MINIFORGE_VERSION"
    log "uv version:         $UV_VERSION"
}

# -- Phase: apt deps -----------------------------------------------------
install_apt_deps() {
    step "apt: build deps"
    if [[ $CHECK_ONLY -eq 1 ]]; then
        log "(check-only mode; skipping apt install)"
        return
    fi
    # Run apt-get update only when the cache is older than 1 day, so that
    # repeated runs on the same box don't repeat the (slow) refresh.
    local last_update_age=999999
    if [[ -f /var/cache/apt/pkgcache.bin ]]; then
        last_update_age=$(( $(date +%s) - $(stat -c %Y /var/cache/apt/pkgcache.bin) ))
    fi
    if (( last_update_age > 86400 )); then
        sudo apt-get update -y
    else
        log "apt cache is fresh (age ${last_update_age}s); skipping update"
    fi
    sudo apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl wget git git-lfs \
        unzip pkg-config tmux
    if ! git lfs install --skip-repo; then
        err "git lfs install failed; weight downloads may not work"
        exit 1
    fi
    ok "apt deps installed"
}

# -- Phase: miniforge / mamba -------------------------------------------
install_miniforge() {
    step "Miniforge $MINIFORGE_VERSION"
    if [[ -x "$CONDA_ROOT/bin/conda" ]]; then
        ok "Miniforge already at $CONDA_ROOT"
        return
    fi
    if [[ $CHECK_ONLY -eq 1 ]]; then
        warn "Miniforge missing"
        return
    fi
    local arch installer url
    arch="$(uname -m)"
    installer="Miniforge3-${MINIFORGE_VERSION}-Linux-${arch}.sh"
    # Use a versioned (not "latest") release tag for reproducibility.
    url="https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/${installer}"
    log "downloading $installer (HTTPS, version-pinned)"
    curl -fsSL -o "/tmp/$installer" "$url"
    bash "/tmp/$installer" -b -p "$CONDA_ROOT"
    rm "/tmp/$installer"
    ok "Miniforge installed at $CONDA_ROOT"
}

conda_run() {
    local env_name="$1"; shift
    "$CONDA_ROOT/bin/conda" run -n "$env_name" "$@"
}

# -- Phase: uv -----------------------------------------------------------
install_uv() {
    step "uv $UV_VERSION"
    if command -v uv >/dev/null && [[ "$(uv --version 2>/dev/null | awk '{print $2}')" == "$UV_VERSION" ]]; then
        ok "uv $UV_VERSION already on PATH"
        return
    fi
    if [[ $CHECK_ONLY -eq 1 ]]; then
        warn "uv $UV_VERSION missing"
        return
    fi
    # Pin to a specific tagged installer.
    curl -LsSf "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-installer.sh" | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
    ok "uv installed: $(uv --version)"
}

# -- Phase: ProteinClaw Python env --------------------------------------
sync_proteinclaw_python() {
    step "ProteinClaw: uv sync --extra dev"
    if [[ ! -f "$PROTEINCLAW_DIR/pyproject.toml" ]]; then
        err "no pyproject.toml in $PROTEINCLAW_DIR — set PROTEINCLAW_DIR to the repo root"
        exit 1
    fi
    if [[ $CHECK_ONLY -eq 1 ]]; then
        if [[ -d "$PROTEINCLAW_DIR/.venv" ]]; then
            ok "ProteinClaw .venv exists"
        else
            warn "ProteinClaw .venv missing"
        fi
        return
    fi
    ( cd "$PROTEINCLAW_DIR" && uv sync --extra dev )
    ok "ProteinClaw Python env ready"
}

# -- Phase: RFdiffusion --------------------------------------------------
# Each weight URL on http://files.ipd.uw.edu/pub/RFdiffusion/<md5>/<name>
# encodes the file's MD5 in the path. We download via HTTPS where the
# server supports it, then verify each file against the embedded MD5.
# Any mismatch aborts the script — this prevents a swapped weight (which
# would execute via PyTorch's pickle-based loader) from being trusted.
RFDIFF_WEIGHT_URLS=(
    "https://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/60f09a193fb5e5ccdc4980417708dbab/Complex_Fold_base_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/74f51cfb8b440f50d70878e05361d8f0/InpaintSeq_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/76d00716416567174cdb7ca96e208296/InpaintSeq_Fold_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/5532d2e1f3a4738decd58b19d633b3c3/ActiveSite_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/12fc204edeae5b57713c5ad7dcb97d39/Base_epoch8_ckpt.pt"
    "https://files.ipd.uw.edu/pub/RFdiffusion/f572d396fae9206628714fb2ce00f72e/Complex_beta_ckpt.pt"
)

verify_rfdiff_weight() {
    local file="$1" url="$2"
    # Extract MD5 from the URL (path segment before the filename).
    local expected
    expected="$(printf '%s' "$url" | awk -F'/' '{print $(NF-1)}')"
    local actual
    actual="$(md5sum "$file" | awk '{print $1}')"
    if [[ "$actual" != "$expected" ]]; then
        err "checksum mismatch for $file"
        err "  expected: $expected"
        err "  actual:   $actual"
        rm -f "$file"
        return 1
    fi
    return 0
}

download_rfdiff_weights() {
    local target_dir="$1"
    mkdir -p "$target_dir"
    log "downloading RFdiffusion weights (HTTPS, MD5-verified, ~10 GB)"
    local url filename
    for url in "${RFDIFF_WEIGHT_URLS[@]}"; do
        filename="$(basename "$url")"
        local out="$target_dir/$filename"
        if [[ -f "$out" ]] && verify_rfdiff_weight "$out" "$url"; then
            ok "$filename: already present, MD5 verified"
            continue
        fi
        wget -q --show-progress -O "$out" "$url"
        if ! verify_rfdiff_weight "$out" "$url"; then
            err "rejecting $filename — refusing to load a tampered checkpoint"
            exit 1
        fi
        ok "$filename: downloaded + MD5 verified"
    done
}

install_rfdiffusion() {
    step "RFdiffusion (conda env + repo + weights)"
    if [[ $INSTALL_RFDIFFUSION -eq 0 ]]; then
        log "skipping RFdiffusion (--skip-rfdiffusion)"
        return
    fi
    local env_name="proteinclaw-rfdiffusion3"

    if [[ $CHECK_ONLY -eq 1 ]]; then
        if conda_env_exists "$env_name"; then ok "RFdiffusion conda env present"; else warn "RFdiffusion conda env missing"; fi
        if [[ -d "$RFDIFFUSION_DIR" ]]; then ok "RFdiffusion repo at $RFDIFFUSION_DIR"; else warn "RFdiffusion repo missing"; fi
        if [[ -d "$RFDIFFUSION_DIR/models" ]]; then ok "RFdiffusion weights present"; else warn "RFdiffusion weights missing"; fi
        return
    fi

    if ! conda_env_exists "$env_name"; then
        log "creating conda env $env_name from envs/rfdiffusion3.yml"
        "$CONDA_ROOT/bin/mamba" env create -f "$PROTEINCLAW_DIR/envs/rfdiffusion3.yml"
    else
        ok "conda env $env_name already exists"
    fi

    if [[ ! -d "$RFDIFFUSION_DIR" ]]; then
        log "cloning RFdiffusion to $RFDIFFUSION_DIR"
        git clone https://github.com/RosettaCommons/RFdiffusion "$RFDIFFUSION_DIR"
    else
        ok "RFdiffusion repo already at $RFDIFFUSION_DIR"
    fi

    download_rfdiff_weights "$RFDIFFUSION_DIR/models"

    log "installing the rfdiffusion package inside the env"
    if ! conda_run "$env_name" pip install -e "$RFDIFFUSION_DIR"; then
        err "rfdiffusion editable install failed; aborting"
        exit 1
    fi

    ok "RFdiffusion ready"
}

# -- Phase: ProteinMPNN --------------------------------------------------
install_protein_mpnn() {
    step "ProteinMPNN (conda env + repo)"
    if [[ $INSTALL_PROTEIN_MPNN -eq 0 ]]; then
        log "skipping ProteinMPNN (--skip-protein-mpnn)"
        return
    fi
    local env_name="proteinclaw-protein-mpnn"

    if [[ $CHECK_ONLY -eq 1 ]]; then
        if conda_env_exists "$env_name"; then ok "ProteinMPNN conda env present"; else warn "ProteinMPNN conda env missing"; fi
        if [[ -d "$PROTEIN_MPNN_DIR" ]]; then ok "ProteinMPNN repo at $PROTEIN_MPNN_DIR"; else warn "ProteinMPNN repo missing"; fi
        return
    fi

    if ! conda_env_exists "$env_name"; then
        log "creating conda env $env_name from envs/protein_mpnn.yml"
        "$CONDA_ROOT/bin/mamba" env create -f "$PROTEINCLAW_DIR/envs/protein_mpnn.yml"
    else
        ok "conda env $env_name already exists"
    fi

    if [[ ! -d "$PROTEIN_MPNN_DIR" ]]; then
        log "cloning ProteinMPNN to $PROTEIN_MPNN_DIR"
        git clone https://github.com/dauparas/ProteinMPNN "$PROTEIN_MPNN_DIR"
    else
        ok "ProteinMPNN repo already at $PROTEIN_MPNN_DIR"
    fi
    ok "ProteinMPNN ready"
}

# -- Phase: ColabFold (optional) ----------------------------------------
install_colabfold() {
    step "ColabFold (optional)"
    if [[ $INSTALL_COLABFOLD -eq 0 ]]; then
        log "skipping ColabFold (use --with-colabfold to install)"
        return
    fi
    local env_name="proteinclaw-colabfold"

    if [[ $CHECK_ONLY -eq 1 ]]; then
        if conda_env_exists "$env_name"; then ok "ColabFold env present"; else warn "ColabFold env missing"; fi
        return
    fi

    if ! conda_env_exists "$env_name"; then
        log "creating conda env $env_name from envs/colabfold.yml"
        "$CONDA_ROOT/bin/mamba" env create -f "$PROTEINCLAW_DIR/envs/colabfold.yml"
    else
        ok "ColabFold env already exists"
    fi
    ok "ColabFold ready"
}

# -- Phase: env file -----------------------------------------------------
write_env_file() {
    step "Writing env vars to $ENV_FILE"
    if [[ $CHECK_ONLY -eq 1 ]]; then
        if [[ -f "$ENV_FILE" ]]; then ok "env file present"; else warn "env file missing"; fi
        return
    fi

    local rfdiff_python="" mpnn_python="" colabfold_bin=""
    if [[ -d "$CONDA_ROOT/envs/proteinclaw-rfdiffusion3" ]]; then
        rfdiff_python="$CONDA_ROOT/envs/proteinclaw-rfdiffusion3/bin/python"
    fi
    if [[ -d "$CONDA_ROOT/envs/proteinclaw-protein-mpnn" ]]; then
        mpnn_python="$CONDA_ROOT/envs/proteinclaw-protein-mpnn/bin/python"
    fi
    if [[ -x "$CONDA_ROOT/envs/proteinclaw-colabfold/bin/colabfold_batch" ]]; then
        colabfold_bin="$CONDA_ROOT/envs/proteinclaw-colabfold/bin/colabfold_batch"
    fi

    cat > "$ENV_FILE" <<EOF
# ProteinClaw env vars — written by scripts/lambda_labs_setup.sh
# Source this from your shell rc: echo 'source $ENV_FILE' >> ~/.bashrc
# Toolchain pins at write time: miniforge=$MINIFORGE_VERSION uv=$UV_VERSION
export PATH="\$HOME/.local/bin:$CONDA_ROOT/bin:\$PATH"
export PROTEINCLAW_BACKEND=auto
export RFDIFFUSION_PATH="$RFDIFFUSION_DIR"
export PROTEINMPNN_PATH="$PROTEIN_MPNN_DIR"
EOF
    [[ -n "$rfdiff_python" ]] && echo "export PROTEINCLAW_RFDIFFUSION_PYTHON=\"$rfdiff_python\"" >> "$ENV_FILE"
    [[ -n "$mpnn_python" ]] && echo "export PROTEINCLAW_PROTEIN_MPNN_PYTHON=\"$mpnn_python\"" >> "$ENV_FILE"
    [[ -n "$colabfold_bin" ]] && echo "export COLABFOLD_BIN=\"$colabfold_bin\"" >> "$ENV_FILE"
    ok "wrote $ENV_FILE"
}

# -- Phase: verify -------------------------------------------------------
verify() {
    step "Verify"
    log "GPU:"
    if command -v nvidia-smi >/dev/null; then
        nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
    fi
    if [[ -d "$CONDA_ROOT/envs/proteinclaw-rfdiffusion3" ]]; then
        local p="$CONDA_ROOT/envs/proteinclaw-rfdiffusion3/bin/python"
        log "PyTorch + CUDA from RFdiffusion env:"
        "$p" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'devices', torch.cuda.device_count())" \
            || warn "torch import failed in RFdiffusion env"
    fi
    log "Done. Next step: source $ENV_FILE then run scripts/smoke_test.sh"
}

# -- main ----------------------------------------------------------------
preflight
install_apt_deps
install_miniforge
install_uv
sync_proteinclaw_python
install_rfdiffusion
install_protein_mpnn
install_colabfold
write_env_file
verify

printf '\n%sNext steps:%s\n' "$BOLD" "$NC"
printf '  1. %ssource %s%s\n' "$GREEN" "$ENV_FILE" "$NC"
printf '  2. %sbash scripts/smoke_test.sh%s   # per-tool manual checks\n' "$GREEN" "$NC"
printf '  3. %suv run pytest -m expensive%s   # ProteinClaw end-to-end via real backends\n' "$GREEN" "$NC"

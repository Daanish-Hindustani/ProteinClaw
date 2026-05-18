#!/usr/bin/env bash
#
# ProteinClaw cluster setup without sudo.
#
# Use this on HPC/cluster GPU nodes where NVIDIA drivers and basic build
# tools are already provided by admins, but apt/sudo is unavailable.
#
# Installs only into user-writable locations:
#   - $INSTALL_PREFIX/miniforge3
#   - $INSTALL_PREFIX/RFdiffusion
#   - $INSTALL_PREFIX/ProteinMPNN
#   - ~/.proteinclaw_env
#
# Env vars you can set:
#   INSTALL_PREFIX       default $HOME/proteinclaw-tools
#   PROTEINCLAW_DIR      default $(pwd)
#   MINIFORGE_VERSION    default 25.3.0-3
#   UV_VERSION           default 0.5.13

set -euo pipefail

HELP=$(cat <<'EOF'
ProteinClaw cluster setup, no sudo

Usage:
  ./scripts/cluster_setup_no_sudo.sh
  ./scripts/cluster_setup_no_sudo.sh --check
  ./scripts/cluster_setup_no_sudo.sh --skip-rfdiffusion
  ./scripts/cluster_setup_no_sudo.sh --skip-protein-mpnn
  ./scripts/cluster_setup_no_sudo.sh --with-colabfold
  ./scripts/cluster_setup_no_sudo.sh -h | --help

Run from the ProteinClaw repo root on a GPU allocation. This script never
uses sudo or apt.
EOF
)

MINIFORGE_VERSION="${MINIFORGE_VERSION:-25.3.0-3}"
UV_VERSION="${UV_VERSION:-0.5.13}"

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

INSTALL_PREFIX="${INSTALL_PREFIX:-$HOME/proteinclaw-tools}"
PROTEINCLAW_DIR="${PROTEINCLAW_DIR:-$(pwd)}"
ENV_FILE="$HOME/.proteinclaw_env"

CONDA_ROOT="$INSTALL_PREFIX/miniforge3"
RFDIFFUSION_DIR="$INSTALL_PREFIX/RFdiffusion"
PROTEIN_MPNN_DIR="$INSTALL_PREFIX/ProteinMPNN"

mkdir -p "$INSTALL_PREFIX"

conda_env_exists() {
    local name="$1"
    [[ -x "$CONDA_ROOT/bin/conda" ]] || return 1
    "$CONDA_ROOT/bin/conda" env list 2>/dev/null \
        | awk '{print $1}' \
        | grep -qE "^${name}$"
}

conda_run() {
    local env_name="$1"; shift
    "$CONDA_ROOT/bin/conda" run -n "$env_name" "$@"
}

require_command() {
    local cmd="$1"
    if command -v "$cmd" >/dev/null; then
        ok "$cmd on PATH: $(command -v "$cmd")"
        return
    fi
    err "$cmd is required but not on PATH"
    exit 1
}

preflight() {
    step "Preflight"
    if [[ "$(uname -s)" != "Linux" ]]; then
        err "this script is for Linux clusters; you ran it on $(uname -s)"
        exit 1
    fi
    for cmd in git curl wget gcc g++ make; do
        require_command "$cmd"
    done
    if command -v nvidia-smi >/dev/null; then
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
        ok "NVIDIA driver detected"
    else
        warn "nvidia-smi is not on PATH; setup can continue, but RFdiffusion smoke tests need a GPU node"
    fi
    log "ProteinClaw repo:   $PROTEINCLAW_DIR"
    log "Tool install root:  $INSTALL_PREFIX"
    log "Env file:           $ENV_FILE"
    log "Miniforge version:  $MINIFORGE_VERSION"
    log "uv version:         $UV_VERSION"
}

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
    url="https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/${installer}"
    log "downloading $installer"
    curl -fsSL -o "/tmp/$installer" "$url"
    bash "/tmp/$installer" -b -p "$CONDA_ROOT"
    rm -f "/tmp/$installer"
    ok "Miniforge installed at $CONDA_ROOT"
}

install_uv() {
    step "uv $UV_VERSION"
    if command -v uv >/dev/null; then
        log "existing uv: $(uv --version)"
        return
    fi
    if [[ $CHECK_ONLY -eq 1 ]]; then
        warn "uv missing"
        return
    fi
    curl -LsSf "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-installer.sh" | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
    ok "uv installed: $(uv --version)"
}

sync_proteinclaw_python() {
    step "ProteinClaw: uv sync --extra dev"
    if [[ ! -f "$PROTEINCLAW_DIR/pyproject.toml" ]]; then
        err "no pyproject.toml in $PROTEINCLAW_DIR; set PROTEINCLAW_DIR to the repo root"
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

MIN_RFDIFF_WEIGHT_BYTES=$((50 * 1024 * 1024))
RFDIFF_MANIFEST_NAME="MD5SUMS.txt"

manifest_lookup() {
    local filename="$1" manifest="$2"
    [[ -f "$manifest" ]] || return 0
    awk -v f="$filename" '$2 == f {print $1; exit}' "$manifest"
}

manifest_record() {
    local filename="$1" md5="$2" manifest="$3"
    if [[ -f "$manifest" ]]; then
        grep -v "  $filename$" "$manifest" > "$manifest.tmp" || true
        mv "$manifest.tmp" "$manifest"
    fi
    printf '%s  %s\n' "$md5" "$filename" >> "$manifest"
}

verify_rfdiff_weight() {
    local file="$1" manifest="$2"
    local filename size actual recorded
    filename="$(basename "$file")"
    size="$(stat -c %s "$file" 2>/dev/null || stat -f %z "$file" 2>/dev/null)"
    if [[ -z "$size" ]] || (( size < MIN_RFDIFF_WEIGHT_BYTES )); then
        err "$filename: size ${size:-unknown} bytes is below the ${MIN_RFDIFF_WEIGHT_BYTES}-byte floor"
        return 1
    fi
    actual="$(md5sum "$file" | awk '{print $1}')"
    recorded="$(manifest_lookup "$filename" "$manifest")"
    if [[ -n "$recorded" ]]; then
        [[ "$actual" == "$recorded" ]] && return 0
        err "$filename: MD5 changed since first install"
        err "  manifest: $recorded"
        err "  current:  $actual"
        return 1
    fi
    manifest_record "$filename" "$actual" "$manifest"
    log "$filename: recorded MD5 $actual in $manifest"
}

download_rfdiff_weights() {
    local target_dir="$1"
    mkdir -p "$target_dir"
    local manifest="$target_dir/$RFDIFF_MANIFEST_NAME"
    local url filename out
    log "downloading RFdiffusion weights (~10 GB)"
    for url in "${RFDIFF_WEIGHT_URLS[@]}"; do
        filename="$(basename "$url")"
        out="$target_dir/$filename"
        if [[ -f "$out" ]] && verify_rfdiff_weight "$out" "$manifest"; then
            ok "$filename already present"
            continue
        fi
        wget -q --show-progress -O "$out" "$url"
        if ! verify_rfdiff_weight "$out" "$manifest"; then
            rm -f "$out"
            err "rejecting $filename; verification failed"
            exit 1
        fi
        ok "$filename downloaded + verified"
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
    local se3_dir="$RFDIFFUSION_DIR/env/SE3Transformer"
    if [[ ! -d "$se3_dir" ]]; then
        err "expected vendored SE3Transformer at $se3_dir"
        exit 1
    fi
    log "installing vendored SE3Transformer"
    conda_run "$env_name" pip install --no-cache-dir "$se3_dir"
    log "installing local RFdiffusion package"
    conda_run "$env_name" pip install --no-cache-dir -e "$RFDIFFUSION_DIR"
    ok "RFdiffusion ready"
}

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

write_env_file() {
    step "Writing env vars to $ENV_FILE"
    if [[ $CHECK_ONLY -eq 1 ]]; then
        if [[ -f "$ENV_FILE" ]]; then ok "env file present"; else warn "env file missing"; fi
        return
    fi
    local rfdiff_python="" mpnn_python="" colabfold_bin=""
    [[ -d "$CONDA_ROOT/envs/proteinclaw-rfdiffusion3" ]] \
        && rfdiff_python="$CONDA_ROOT/envs/proteinclaw-rfdiffusion3/bin/python"
    [[ -d "$CONDA_ROOT/envs/proteinclaw-protein-mpnn" ]] \
        && mpnn_python="$CONDA_ROOT/envs/proteinclaw-protein-mpnn/bin/python"
    [[ -x "$CONDA_ROOT/envs/proteinclaw-colabfold/bin/colabfold_batch" ]] \
        && colabfold_bin="$CONDA_ROOT/envs/proteinclaw-colabfold/bin/colabfold_batch"

    cat > "$ENV_FILE" <<EOF
# ProteinClaw env vars - written by scripts/cluster_setup_no_sudo.sh
# Source this with: source $ENV_FILE
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

verify_torch_in_env() {
    local env_label="$1" python_path="$2"
    if [[ ! -x "$python_path" ]]; then
        warn "$env_label python missing at $python_path"
        return
    fi
    log "$env_label: PyTorch + CUDA"
    if "$python_path" -c "import torch; print('torch', torch.__version__); print('cuda', torch.cuda.is_available(), 'devices', torch.cuda.device_count()); raise SystemExit(0 if torch.cuda.is_available() else 1)"; then
        ok "$env_label CUDA visible"
    else
        warn "$env_label CUDA not visible; check GPU allocation/CUDA compatibility"
    fi
}

verify_tools() {
    step "Verify"
    if [[ $CHECK_ONLY -eq 1 ]]; then
        log "(check-only; skipping verification)"
        return
    fi
    [[ $INSTALL_RFDIFFUSION -eq 1 ]] && verify_torch_in_env "RFdiffusion env" "$CONDA_ROOT/envs/proteinclaw-rfdiffusion3/bin/python"
    [[ $INSTALL_PROTEIN_MPNN -eq 1 ]] && verify_torch_in_env "ProteinMPNN env" "$CONDA_ROOT/envs/proteinclaw-protein-mpnn/bin/python"
    if [[ -f "$ENV_FILE" ]]; then
        ok "env file present"
    else
        err "env file missing after setup"
        exit 1
    fi
}

preflight
install_miniforge
install_uv
sync_proteinclaw_python
install_rfdiffusion
install_protein_mpnn
install_colabfold
write_env_file
verify_tools

printf '\n%sNext steps:%s\n' "$BOLD" "$NC"
printf '  1. %ssource %s%s\n' "$GREEN" "$ENV_FILE" "$NC"
printf '  2. %sbash scripts/smoke_test.sh%s\n' "$GREEN" "$NC"
printf '  3. %suv run proteinclaw doctor%s\n' "$GREEN" "$NC"

#!/usr/bin/env bash
# Set up local Docker images for the Hermes protein-design plugin.
#
# This script does not install Hermes. It is safe to call from `hermes setup`
# after the Python environment already exists.

set -euo pipefail

FOUNDRY_IMAGE_DEFAULT="rosettacommons/foundry:latest"
ESMFOLD_IMAGE_DEFAULT="hermes-esmfold:latest"
ALPHAFOLD2_IMAGE_DEFAULT="ghcr.io/sokrypton/colabfold:1.6.1-cuda12"
ALPHAFOLD2_COMMAND_DEFAULT="colabfold_batch"

FOUNDRY_IMAGE="${HERMES_PROTEIN_FOUNDRY_IMAGE:-$FOUNDRY_IMAGE_DEFAULT}"
ESMFOLD_IMAGE="${HERMES_PROTEIN_ESMFOLD_IMAGE:-$ESMFOLD_IMAGE_DEFAULT}"
ALPHAFOLD2_IMAGE="${HERMES_PROTEIN_ALPHAFOLD2_IMAGE:-$ALPHAFOLD2_IMAGE_DEFAULT}"
ALPHAFOLD2_COMMAND="${HERMES_PROTEIN_ALPHAFOLD2_COMMAND:-$ALPHAFOLD2_COMMAND_DEFAULT}"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
SKIP_FOUNDRY=0
SKIP_ESMFOLD_BUILD=0
SKIP_ALPHAFOLD2=0
SKIP_SMOKE_TESTS=0
INSTALL_NVIDIA_DRIVER="${HERMES_PROTEIN_INSTALL_NVIDIA_DRIVER:-auto}"
NVIDIA_DRIVER_PACKAGE="${HERMES_PROTEIN_NVIDIA_DRIVER_PACKAGE:-auto}"

usage() {
  cat <<'EOF'
Usage: scripts/setup_protein_design_local.sh [options]

Options:
  --skip-foundry        Do not pull/check the Foundry image for RFD3/ProteinMPNN
  --skip-esmfold-build  Do not build/check the local ESMFold image
  --skip-alphafold2     Do not pull/check the AlphaFold2/ColabFold image
  --skip-smoke-tests    Do not run GPU/tool smoke tests after pull/build
  --install-nvidia-driver
                        Install the recommended Ubuntu NVIDIA compute driver if missing
  --no-install-nvidia-driver
                        Do not prompt to install an NVIDIA driver
  --driver-package PKG  Install a specific driver package instead of ubuntu-drivers auto-detect
  -h, --help            Show this help

Environment overrides:
  HERMES_HOME                            Default: ~/.hermes
  HERMES_PROTEIN_FOUNDRY_IMAGE           Default: rosettacommons/foundry:latest
  HERMES_PROTEIN_ESMFOLD_IMAGE           Default: hermes-esmfold:latest
  HERMES_PROTEIN_ALPHAFOLD2_IMAGE        Default: ghcr.io/sokrypton/colabfold:1.6.1-cuda12
  HERMES_PROTEIN_ALPHAFOLD2_COMMAND      Default: colabfold_batch
  HERMES_PROTEIN_WORKSPACE_ROOT          Default: $HERMES_HOME/protein-design
  HERMES_PROTEIN_DEFAULT_TIMEOUT_SECONDS Default: 7200
  HERMES_PROTEIN_INSTALL_NVIDIA_DRIVER   auto|1|0, default: auto
  HERMES_PROTEIN_NVIDIA_DRIVER_PACKAGE   Default: auto
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-foundry) SKIP_FOUNDRY=1 ;;
    --skip-esmfold-build) SKIP_ESMFOLD_BUILD=1 ;;
    --skip-alphafold2) SKIP_ALPHAFOLD2=1 ;;
    --skip-smoke-tests) SKIP_SMOKE_TESTS=1 ;;
    --install-nvidia-driver) INSTALL_NVIDIA_DRIVER=1 ;;
    --no-install-nvidia-driver) INSTALL_NVIDIA_DRIVER=0 ;;
    --driver-package)
      shift
      if [[ $# -eq 0 ]]; then
        echo "--driver-package requires a package name" >&2
        exit 2
      fi
      NVIDIA_DRIVER_PACKAGE="$1"
      INSTALL_NVIDIA_DRIVER=1
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf '\nWARN: %s\n' "$*" >&2
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

is_falsey() {
  case "${1:-}" in
    0|false|FALSE|no|NO|n|N|off|OFF) return 0 ;;
    *) return 1 ;;
  esac
}

prompt_yes_no() {
  local question="$1"
  local default="${2:-no}"
  local prompt="[y/N]"
  if [[ "$default" == "yes" ]]; then
    prompt="[Y/n]"
  fi

  if [[ ! -t 0 ]]; then
    [[ "$default" == "yes" ]]
    return
  fi

  local reply
  read -r -p "$question $prompt " reply
  reply="${reply:-$default}"
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo docker "$@"
  else
    docker "$@"
  fi
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for local protein-design compute." >&2
    echo "Install Docker and NVIDIA Container Toolkit, then rerun this script." >&2
    exit 1
  fi
  docker_cmd version >/dev/null
}

is_ubuntu() {
  [[ -r /etc/os-release ]] || return 1
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]]
}

has_nvidia_pci_device() {
  command -v lspci >/dev/null 2>&1 || return 2
  lspci | grep -qi "nvidia"
}

host_nvidia_smi_works() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/tmp/hermes-host-nvidia-smi.txt 2>&1
}

install_nvidia_smi_utils() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    return 0
  fi

  log "Installing NVIDIA user-space utilities for nvidia-smi"
  sudo apt-get update
  local candidates=()
  local installed_pkg
  while IFS= read -r installed_pkg; do
    [[ -n "$installed_pkg" ]] || continue
    local suffix=""
    case "$installed_pkg" in
      nvidia-driver-*) suffix="${installed_pkg#nvidia-driver-}" ;;
      nvidia-headless-*) suffix="${installed_pkg#nvidia-headless-}" ;;
      nvidia-headless-no-dkms-*) suffix="${installed_pkg#nvidia-headless-no-dkms-}" ;;
      nvidia-dkms-*) suffix="${installed_pkg#nvidia-dkms-}" ;;
      libnvidia-compute-*) suffix="${installed_pkg#libnvidia-compute-}" ;;
    esac
    [[ -n "$suffix" ]] || continue
    candidates+=(
      "nvidia-utils-$suffix"
      "nvidia-compute-utils-$suffix"
    )
    if [[ "$suffix" != *-server ]]; then
      candidates+=(
        "nvidia-utils-$suffix-server"
        "nvidia-compute-utils-$suffix-server"
      )
    fi
  done < <(
    dpkg-query -W -f='${binary:Package}\n' \
      'nvidia-driver-*' \
      'nvidia-headless-*' \
      'nvidia-headless-no-dkms-*' \
      'nvidia-dkms-*' \
      'libnvidia-compute-*' 2>/dev/null || true
  )

  if [[ "$NVIDIA_DRIVER_PACKAGE" == nvidia-driver-* ]]; then
    local explicit_suffix="${NVIDIA_DRIVER_PACKAGE#nvidia-driver-}"
    candidates=(
      "nvidia-utils-$explicit_suffix"
      "nvidia-compute-utils-$explicit_suffix"
      "${candidates[@]}"
    )
  elif [[ "$NVIDIA_DRIVER_PACKAGE" == nvidia-headless-* ]]; then
    local explicit_suffix="${NVIDIA_DRIVER_PACKAGE#nvidia-headless-}"
    candidates=(
      "nvidia-utils-$explicit_suffix"
      "nvidia-compute-utils-$explicit_suffix"
      "${candidates[@]}"
    )
  fi

  local pkg
  local seen=" "
  for pkg in "${candidates[@]}"; do
    [[ "$seen" == *" $pkg "* ]] && continue
    seen+="$pkg "
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      sudo apt-get install -y "$pkg"
      if command -v nvidia-smi >/dev/null 2>&1; then
        return 0
      fi
    fi
  done

  local fallback
  fallback="$(
    apt-cache search '^nvidia-utils-[0-9]+(-server)?$' \
      | awk '{print $1}' \
      | sort -V \
      | tail -1
  )"
  if [[ -n "$fallback" ]]; then
    sudo apt-get install -y "$fallback"
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  warn "Could not install nvidia-smi automatically. Inspect installed NVIDIA packages with:"
  warn "  dpkg -l | grep -E 'nvidia|libnvidia'"
  return 1
}

install_nvidia_driver() {
  if ! is_ubuntu; then
    warn "Automatic NVIDIA driver installation is only implemented for Ubuntu."
    warn "Install the driver manually, then verify: nvidia-smi"
    return 1
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    warn "sudo is required to install the NVIDIA driver automatically."
    return 1
  fi

  log "Installing NVIDIA driver packages"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    ubuntu-drivers-common \
    pciutils \
    "linux-headers-$(uname -r)"

  if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi enabled; then
    warn "Secure Boot appears to be enabled. Ubuntu may prompt for MOK enrollment during driver installation."
  fi

  log "Available NVIDIA compute drivers"
  sudo ubuntu-drivers list --gpgpu || true

  if [[ "$NVIDIA_DRIVER_PACKAGE" != "auto" ]]; then
    sudo apt-get install -y "$NVIDIA_DRIVER_PACKAGE"
  else
    sudo ubuntu-drivers install --gpgpu
  fi
  install_nvidia_smi_utils || true

  cat <<EOF

NVIDIA driver installation finished.

A reboot is normally required before nvidia-smi and Docker GPU containers work:
  sudo reboot

After reboot, rerun:
  scripts/setup_protein_design_local.sh

EOF
  return 0
}

ensure_nvidia_driver() {
  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return 0
  fi
  if host_nvidia_smi_works; then
    return 0
  fi
  if is_ubuntu && dpkg-query -W 'nvidia-*' 'libnvidia-*' >/dev/null 2>&1; then
    warn "NVIDIA packages are installed, but nvidia-smi is missing or failing. Installing user-space utilities."
    install_nvidia_smi_utils || true
    if host_nvidia_smi_works; then
      return 0
    fi
  fi

  warn "The host NVIDIA driver is not working. RFD3, ProteinMPNN, and ESMFold need a working driver for local GPU compute."
  if has_nvidia_pci_device; then
    warn "An NVIDIA PCI device was detected, but nvidia-smi is unavailable or failing."
  else
    case $? in
      1) warn "No NVIDIA PCI device was detected. Make sure this is a GPU machine before installing drivers." ;;
      2) warn "lspci is unavailable, so GPU hardware detection was skipped." ;;
    esac
  fi

  if is_truthy "$INSTALL_NVIDIA_DRIVER"; then
    install_nvidia_driver
    return 2
  fi
  if is_falsey "$INSTALL_NVIDIA_DRIVER"; then
    return 1
  fi
  if prompt_yes_no "Install the recommended Ubuntu NVIDIA compute driver now? This requires sudo and usually a reboot." "yes"; then
    install_nvidia_driver
    return 2
  fi
  return 1
}

write_config() {
  log "Writing protein-design local compute config"
  mkdir -p "$HERMES_HOME_DIR"

  local config_python="python3"
  if [[ -x "$REPO_ROOT/venv/bin/python" ]]; then
    config_python="$REPO_ROOT/venv/bin/python"
  elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    config_python="$REPO_ROOT/.venv/bin/python"
  fi

  HERMES_HOME="$HERMES_HOME_DIR" "$config_python" - <<'PY'
import os
from pathlib import Path

import yaml

home = Path(os.environ["HERMES_HOME"]).expanduser()
config_path = home / "config.yaml"
config = {}
if config_path.exists():
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

plugins = config.setdefault("plugins", {})
enabled = plugins.setdefault("enabled", [])
if "protein-design" not in enabled:
    enabled.append("protein-design")

protein = config.setdefault("protein_design", {})
protein["foundry_image"] = os.environ.get("HERMES_PROTEIN_FOUNDRY_IMAGE", "rosettacommons/foundry:latest")
protein["esmfold_image"] = os.environ.get("HERMES_PROTEIN_ESMFOLD_IMAGE", "hermes-esmfold:latest")
protein["alphafold2_image"] = os.environ.get("HERMES_PROTEIN_ALPHAFOLD2_IMAGE", "ghcr.io/sokrypton/colabfold:1.6.1-cuda12")
protein["alphafold2_command"] = os.environ.get("HERMES_PROTEIN_ALPHAFOLD2_COMMAND", "colabfold_batch")
protein.setdefault("workspace_root", os.environ.get("HERMES_PROTEIN_WORKSPACE_ROOT", str(home / "protein-design")))
protein.setdefault("default_timeout_seconds", int(os.environ.get("HERMES_PROTEIN_DEFAULT_TIMEOUT_SECONDS", "7200")))

config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
print(config_path)
PY
}

check_gpu_runtime() {
  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return 0
  fi

  log "Checking host NVIDIA driver"
  if ! host_nvidia_smi_works; then
    warn "Host nvidia-smi failed. Inspect /tmp/hermes-host-nvidia-smi.txt and fix the NVIDIA driver before running local protein-design compute."
    return 1
  fi

  log "Checking Docker GPU runtime"
  if ! docker_cmd run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; then
    if command -v nvidia-ctk >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
      warn "Docker GPU check failed. Reconfiguring NVIDIA Container Toolkit and retrying once."
      sudo nvidia-ctk runtime configure --runtime=docker || true
      sudo systemctl restart docker || true
      if docker_cmd run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; then
        return 0
      fi
    fi
    warn "Docker GPU check failed. The host driver may be missing, NVIDIA Container Toolkit may be misconfigured, or Docker may need restart."
    warn "If the error mentions libnvidia-ml.so.1, fix the host NVIDIA driver first."
    return 1
  fi
  return 0
}

setup_foundry() {
  if [[ "$SKIP_FOUNDRY" == "1" ]]; then
    log "Skipping Foundry image"
    return
  fi

  log "Pulling Foundry image: $FOUNDRY_IMAGE"
  docker_cmd pull "$FOUNDRY_IMAGE"

  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return
  fi

  log "Checking Foundry commands"
  docker_cmd run --rm --gpus all "$FOUNDRY_IMAGE" rfd3 --help >/tmp/hermes-rfd3-help.txt
  docker_cmd run --rm --gpus all "$FOUNDRY_IMAGE" mpnn --help >/tmp/hermes-mpnn-help.txt || \
    warn "Foundry mpnn --help failed. The image may still work depending on its entrypoint; inspect /tmp/hermes-mpnn-help.txt."
}

setup_esmfold() {
  if [[ "$SKIP_ESMFOLD_BUILD" == "1" ]]; then
    log "Skipping ESMFold image build"
    return
  fi

  log "Building ESMFold image: $ESMFOLD_IMAGE"
  docker_cmd build \
    -t "$ESMFOLD_IMAGE" \
    -f plugins/protein-design/docker/esmfold.Dockerfile \
    plugins/protein-design/docker

  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return
  fi

  log "Checking ESMFold image entrypoint"
  docker_cmd run --rm --entrypoint python3 "$ESMFOLD_IMAGE" \
    -c "import sys; sys.path.insert(0, '/opt'); import implementation; print('esmfold image ok')" \
    >/tmp/hermes-esmfold-help.txt
}

setup_alphafold2() {
  if [[ "$SKIP_ALPHAFOLD2" == "1" ]]; then
    log "Skipping AlphaFold2/ColabFold image"
    return
  fi

  log "Pulling AlphaFold2/ColabFold image: $ALPHAFOLD2_IMAGE"
  docker_cmd pull "$ALPHAFOLD2_IMAGE"

  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return
  fi

  log "Checking AlphaFold2/ColabFold command"
  docker_cmd run --rm --gpus all "$ALPHAFOLD2_IMAGE" "$ALPHAFOLD2_COMMAND" --help >/tmp/hermes-alphafold2-help.txt || \
    warn "AlphaFold2/ColabFold command check failed. Inspect /tmp/hermes-alphafold2-help.txt or set HERMES_PROTEIN_ALPHAFOLD2_COMMAND."
}

require_docker
write_config
DRIVER_INSTALL_STATUS=0
ensure_nvidia_driver || DRIVER_INSTALL_STATUS=$?
if [[ "$DRIVER_INSTALL_STATUS" == "2" ]]; then
  exit 3
fi
GPU_READY=1
if ! check_gpu_runtime; then
  GPU_READY=0
  SKIP_SMOKE_TESTS=1
  warn "Continuing image pull/build, but skipping GPU command smoke tests."
fi
setup_foundry
setup_esmfold
setup_alphafold2

if [[ "$GPU_READY" == "0" ]]; then
  cat <<EOF

Protein-design images/config were prepared, but local GPU compute is not ready.

Fix NVIDIA driver + Docker GPU runtime, then verify:
  nvidia-smi
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

Then re-run:
  scripts/setup_protein_design_local.sh

EOF
  exit 2
fi

cat <<EOF

Protein-design local compute setup complete.

Configured images:
  Foundry: $FOUNDRY_IMAGE
  ESMFold: $ESMFOLD_IMAGE
  AlphaFold2/ColabFold: $ALPHAFOLD2_IMAGE ($ALPHAFOLD2_COMMAND)

Config:
  $HERMES_HOME_DIR/config.yaml

EOF

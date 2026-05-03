#!/usr/bin/env bash
# Set up a Lambda Labs Ubuntu GPU instance for the Hermes protein-design plugin.
#
# Assumptions:
# - "Lambda" means Lambda Cloud / Lambda Labs GPU VM, not AWS Lambda.
# - The instance is Ubuntu 22.04. If NVIDIA drivers are missing, the script can
#   install the recommended Ubuntu compute driver and ask for a reboot.
# - Run this from the hermes-agent repository root after cloning it.

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
SKIP_HERMES_INSTALL=0
SKIP_IMAGES=0
SKIP_ESMFOLD_BUILD=0
SKIP_ALPHAFOLD2=0
SKIP_DOCKER_SETUP=0
SKIP_SMOKE_TESTS=0
INSTALL_NVIDIA_DRIVER="${HERMES_PROTEIN_INSTALL_NVIDIA_DRIVER:-auto}"
NVIDIA_DRIVER_PACKAGE="${HERMES_PROTEIN_NVIDIA_DRIVER_PACKAGE:-auto}"

usage() {
  cat <<'EOF'
Usage: scripts/setup_protein_design_lambda.sh [options]

Options:
  --skip-hermes-install   Do not run ./setup-hermes.sh
  --skip-docker-setup     Do not install/configure Docker or NVIDIA Container Toolkit
  --skip-images           Do not pull/build protein-design Docker images
  --skip-esmfold-build    Pull Foundry, but do not build the ESMFold image
  --skip-alphafold2       Do not pull/check the AlphaFold2/ColabFold image
  --skip-smoke-tests      Do not run GPU/tool smoke tests after pull/build
  --install-nvidia-driver Install the recommended Ubuntu NVIDIA compute driver if missing
  --no-install-nvidia-driver
                           Do not prompt to install an NVIDIA driver
  --driver-package PKG    Install a specific driver package instead of ubuntu-drivers auto-detect
  -h, --help              Show this help

Environment overrides:
  HERMES_HOME                         Default: ~/.hermes
  HERMES_PROTEIN_FOUNDRY_IMAGE        Default: rosettacommons/foundry:latest
  HERMES_PROTEIN_ESMFOLD_IMAGE        Default: hermes-esmfold:latest
  HERMES_PROTEIN_ALPHAFOLD2_IMAGE     Default: ghcr.io/sokrypton/colabfold:1.6.1-cuda12
  HERMES_PROTEIN_ALPHAFOLD2_COMMAND   Default: colabfold_batch
  HERMES_PROTEIN_WORKSPACE_ROOT       Default: $HERMES_HOME/protein-design
  HERMES_PROTEIN_DEFAULT_TIMEOUT_SECONDS Default: 7200
  HERMES_PROTEIN_INSTALL_NVIDIA_DRIVER   auto|1|0, default: auto
  HERMES_PROTEIN_NVIDIA_DRIVER_PACKAGE   Default: auto
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-hermes-install) SKIP_HERMES_INSTALL=1 ;;
    --skip-docker-setup) SKIP_DOCKER_SETUP=1 ;;
    --skip-images) SKIP_IMAGES=1 ;;
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

require_ubuntu() {
  if [[ ! -r /etc/os-release ]]; then
    warn "Cannot read /etc/os-release; continuing anyway."
    return
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    warn "This script is written for Ubuntu Lambda Cloud instances; detected ID=${ID:-unknown}."
  fi
}

install_base_packages() {
  log "Installing base packages"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    git \
    jq \
    pciutils \
    build-essential \
    python3-venv
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

host_nvidia_smi_works() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/tmp/hermes-lambda-nvidia-smi.txt 2>&1
}

install_nvidia_driver() {
  log "Installing NVIDIA driver packages"
  sudo apt update
  sudo apt-get install -y --no-install-recommends \
    ubuntu-drivers-common \
    pciutils \
    "linux-headers-$(uname -r)"

  if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi enabled; then
    warn "Secure Boot appears to be enabled. Ubuntu may prompt for MOK enrollment during driver installation."
  fi

  log "Detected NVIDIA driver recommendations"
  sudo ubuntu-drivers devices || true

  if [[ "$NVIDIA_DRIVER_PACKAGE" != "auto" ]]; then
    sudo apt-get install -y "$NVIDIA_DRIVER_PACKAGE"
  else
    sudo ubuntu-drivers autoinstall
  fi

  cat <<EOF

NVIDIA driver installation finished.

A reboot is required before nvidia-smi and Docker GPU containers work:
  sudo reboot

After reboot, rerun:
  scripts/setup_protein_design_lambda.sh

EOF
}

ensure_nvidia_driver() {
  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    return 0
  fi
  if host_nvidia_smi_works; then
    log "Host NVIDIA driver is working"
    return 0
  fi

  warn "Host nvidia-smi is missing or failing. Inspect /tmp/hermes-lambda-nvidia-smi.txt if it exists."
  warn "Lambda Cloud GPU instances need a working host NVIDIA driver before Docker GPU runtime can work."

  if is_falsey "$INSTALL_NVIDIA_DRIVER"; then
    return 1
  fi
  if is_truthy "$INSTALL_NVIDIA_DRIVER" || prompt_yes_no "Install the recommended Ubuntu NVIDIA compute driver now? This requires sudo and a reboot." "yes"; then
    install_nvidia_driver
    return 2
  fi
  return 1
}

install_docker_if_missing() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed: $(docker --version)"
  else
    log "Installing Docker from Ubuntu packages"
    sudo apt-get install -y docker.io
  fi

  sudo systemctl enable --now docker

  if ! groups "$USER" | grep -qE '(^| )docker( |$)'; then
    log "Adding $USER to docker group"
    sudo usermod -aG docker "$USER"
    warn "Group membership changes require a new shell/login. This script uses sudo docker when needed."
  fi
}

install_nvidia_container_toolkit() {
  if [[ "$SKIP_DOCKER_SETUP" == "1" ]]; then
    log "Skipping Docker/NVIDIA Container Toolkit setup"
    return
  fi

  install_base_packages
  local driver_status=0
  ensure_nvidia_driver || driver_status=$?
  if [[ "$driver_status" == "2" ]]; then
    exit 3
  fi
  install_docker_if_missing

  if command -v nvidia-ctk >/dev/null 2>&1; then
    log "nvidia-ctk already installed: $(nvidia-ctk --version 2>/dev/null | head -1)"
  else
    log "Installing NVIDIA Container Toolkit"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
  fi

  log "Configuring Docker NVIDIA runtime"
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
}

install_hermes() {
  if [[ "$SKIP_HERMES_INSTALL" == "1" ]]; then
    log "Skipping Hermes install"
    return
  fi

  log "Installing Hermes into repo-local virtualenv"
  ./setup-hermes.sh
}

enable_plugin_config() {
  log "Writing protein-design plugin config"
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
protein.setdefault("foundry_image", os.environ.get("HERMES_PROTEIN_FOUNDRY_IMAGE", "rosettacommons/foundry:latest"))
protein.setdefault("esmfold_image", os.environ.get("HERMES_PROTEIN_ESMFOLD_IMAGE", "hermes-esmfold:latest"))
protein.setdefault("alphafold2_image", os.environ.get("HERMES_PROTEIN_ALPHAFOLD2_IMAGE", "ghcr.io/sokrypton/colabfold:1.6.1-cuda12"))
protein.setdefault("alphafold2_command", os.environ.get("HERMES_PROTEIN_ALPHAFOLD2_COMMAND", "colabfold_batch"))
protein.setdefault("workspace_root", os.environ.get("HERMES_PROTEIN_WORKSPACE_ROOT", str(home / "protein-design")))
protein.setdefault("default_timeout_seconds", int(os.environ.get("HERMES_PROTEIN_DEFAULT_TIMEOUT_SECONDS", "7200")))

config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
print(config_path)
PY
}

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    sudo docker "$@"
  fi
}

verify_gpu_runtime() {
  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    log "Skipping GPU runtime smoke test"
    return
  fi

  log "Checking host GPU"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
  else
    warn "nvidia-smi not found. Lambda Cloud images normally include NVIDIA drivers; check the instance image."
  fi

  log "Checking Docker GPU runtime"
  docker_cmd run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
}

install_images() {
  if [[ "$SKIP_IMAGES" == "1" ]]; then
    log "Skipping protein-design Docker images"
    return
  fi

  local args=()
  if [[ "$SKIP_ESMFOLD_BUILD" == "1" ]]; then
    args+=(--skip-esmfold-build)
  fi
  if [[ "$SKIP_ALPHAFOLD2" == "1" ]]; then
    args+=(--skip-alphafold2)
  fi
  if [[ "$SKIP_SMOKE_TESTS" == "1" ]]; then
    args+=(--skip-smoke-tests)
  fi
  if [[ "$INSTALL_NVIDIA_DRIVER" == "1" ]]; then
    args+=(--install-nvidia-driver)
  elif [[ "$INSTALL_NVIDIA_DRIVER" == "0" ]]; then
    args+=(--no-install-nvidia-driver)
  fi
  if [[ "$NVIDIA_DRIVER_PACKAGE" != "auto" ]]; then
    args+=(--driver-package "$NVIDIA_DRIVER_PACKAGE")
  fi
  scripts/setup_protein_design_local.sh "${args[@]}"
}

print_next_steps() {
  cat <<EOF

Setup complete.

Next steps:
  1. Open a fresh shell if this script added you to the docker group:
       exec su -l "$USER"

  2. Activate Hermes:
       cd "$REPO_ROOT"
       source venv/bin/activate

  3. Start Hermes with the protein toolset available:
       hermes

  4. Smoke-test from Hermes:
       Use pubmed_search to find recent review papers on RFdiffusion protein binder design.
       Use rfd3_design in free_generation mode with output_name "lambda_debug",
       num_designs 1, contig "60-80", guide_scale 1.5, num_timesteps 25.

Config written under:
  $HERMES_HOME_DIR/config.yaml

Protein outputs default to:
  ${HERMES_PROTEIN_WORKSPACE_ROOT:-$HERMES_HOME_DIR/protein-design}

Configured AlphaFold2/ColabFold image:
  $ALPHAFOLD2_IMAGE ($ALPHAFOLD2_COMMAND)

EOF
}

require_ubuntu
install_nvidia_container_toolkit
install_hermes
enable_plugin_config
verify_gpu_runtime
install_images
print_next_steps

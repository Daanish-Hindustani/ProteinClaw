#!/usr/bin/env bash
#
# ProteinClaw — Lambda Labs smoke test.
#
# Walks through each tool in increasing complexity. Each section is a
# manual check you can read, copy, and run on its own. Rather than
# automating everything, the script PRINTS what would run and runs it
# only when you press [enter]; that way you can pause, inspect, or
# repeat a step in isolation.
#
# Run AFTER scripts/lambda_labs_setup.sh and `source ~/.proteinclaw_env`.
#
# Usage:
#   ./scripts/smoke_test.sh             # interactive
#   ./scripts/smoke_test.sh --auto      # run every step without prompts
#   ./scripts/smoke_test.sh --skip-gpu  # skip GPU-dependent tools

set -euo pipefail

INTERACTIVE=1
SKIP_GPU=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto)     INTERACTIVE=0 ;;
        --skip-gpu) SKIP_GPU=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ -t 1 ]]; then
    GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
    GREEN=""; YELLOW=""; BLUE=""; BOLD=""; NC=""
fi

step() { printf '\n%s%s== %s ==%s\n' "$BOLD" "$BLUE" "$*" "$NC"; }
expl() { printf '%sWhat this proves:%s %s\n' "$YELLOW" "$NC" "$*"; }

# `cmd` runs a shell snippet. Many of our snippets need shell features
# (pipes, &&, glob expansion), so we send them through `bash -c`. Any
# values derived from globs/filesystem must be passed as positional
# arguments (so they appear as $1, $2, ... inside the snippet) rather
# than concatenated into the snippet string — otherwise a maliciously
# named file in /tmp could inject commands when the snippet is parsed.
cmd() {
    local snippet="$1"; shift
    printf '%s$ %s%s\n' "$GREEN" "$snippet" "$NC"
    if [[ $INTERACTIVE -eq 1 ]]; then
        read -r -p "press [enter] to run, [s] to skip, [q] to quit: " ans
        case "$ans" in
            s|S) echo "(skipped)"; return 0 ;;
            q|Q) exit 0 ;;
        esac
    fi
    bash -c "$snippet" -- "$@" || printf '%s(non-zero exit)%s\n' "$YELLOW" "$NC"
}

if [[ -z "${PROTEINCLAW_BACKEND:-}" ]]; then
    echo "PROTEINCLAW_BACKEND is not set; did you forget to 'source ~/.proteinclaw_env'?" >&2
fi

# ----------------------------------------------------------------------
step "1. GPU + driver"
expl "the Lambda Stack exposes the GPU and CUDA toolkit to userspace"
cmd  "nvidia-smi"
cmd  "nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader"

# ----------------------------------------------------------------------
step "2. PyTorch sees CUDA (RFdiffusion env)"
expl "PyTorch in the RFdiffusion conda env actually has a CUDA build that matches the driver"
RFDIFF_PY="${PROTEINCLAW_RFDIFFUSION_PYTHON:-}"
if [[ -n "$RFDIFF_PY" ]]; then
    cmd  "$RFDIFF_PY -c \"import torch; print('torch', torch.__version__); print('cuda', torch.cuda.is_available()); print('devices', torch.cuda.device_count())\""
else
    echo "(skipped — PROTEINCLAW_RFDIFFUSION_PYTHON not set)"
fi

# ----------------------------------------------------------------------
step "3. RCSB REST"
expl "the public RCSB Data API is reachable and returns sequence + organism"
cmd  "curl -fsS 'https://data.rcsb.org/rest/v1/core/polymer_entity/4HHB/1' | python -c 'import json,sys; d=json.load(sys.stdin); print(d[\"entity_poly\"][\"pdbx_seq_one_letter_code_can\"][:60]+\"...\")'"

# ----------------------------------------------------------------------
step "4. ESM Atlas REST"
expl "the public ESM Atlas folding endpoint accepts a sequence and returns a PDB"
cmd  "curl -fsS -X POST --data 'MGSSHHHHHHSSGLVPRGSHMRGPNPTAASLEASAGPFTVRSFTVSRPSGYGAGTVYYPTNAGGTV' https://api.esmatlas.com/foldSequence/v1/pdb/ | head -3"

# ----------------------------------------------------------------------
step "5. Foldseek REST (slow — ~1-3 min)"
expl "the Foldseek public server accepts a ticket and runs a search; we just submit and read the ticket id"
cmd  "echo 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 90.00' > /tmp/q.pdb && \
      curl -fsS -F 'q=@/tmp/q.pdb' -F 'database[]=pdb100' -F 'mode=3diaa' https://search.foldseek.com/api/ticket"

if [[ $SKIP_GPU -eq 0 ]]; then

# ----------------------------------------------------------------------
step "6. RFdiffusion direct CLI (~30-90s)"
expl "RFdiffusion's run_inference.py loads weights, runs on the GPU, and writes a PDB. No ProteinClaw involved."
RFDIFF_PATH="${RFDIFFUSION_PATH:-}"
if [[ -n "$RFDIFF_PATH" ]] && [[ -n "$RFDIFF_PY" ]]; then
    # Positional args feed into bash -c as "$1", "$2", ... so that
    # filesystem-derived values can never be parsed as shell syntax.
    cmd '
        mkdir -p /tmp/rfdiff_smoke && \
        "$1" "$2"/scripts/run_inference.py \
            inference.output_prefix=/tmp/rfdiff_smoke/test \
            "contigmap.contigs=[100-100]" \
            inference.num_designs=1 \
            denoiser.noise_scale_ca=0 \
            denoiser.noise_scale_frame=0 && \
        ls -la /tmp/rfdiff_smoke/
    ' "$RFDIFF_PY" "$RFDIFF_PATH"
else
    echo "(skipped — RFDIFFUSION_PATH or PROTEINCLAW_RFDIFFUSION_PYTHON missing)"
fi

# ----------------------------------------------------------------------
step "7. ProteinMPNN direct CLI (~30s)"
expl "ProteinMPNN's protein_mpnn_run.py reads a backbone PDB and writes a FASTA of designed sequences"
MPNN_PATH="${PROTEINMPNN_PATH:-}"
MPNN_PY="${PROTEINCLAW_PROTEIN_MPNN_PYTHON:-}"
shopt -s nullglob
RFDIFF_PDBS=(/tmp/rfdiff_smoke/test_*.pdb)
shopt -u nullglob
if [[ -n "$MPNN_PATH" ]] && [[ -n "$MPNN_PY" ]] && (( ${#RFDIFF_PDBS[@]} > 0 )); then
    BACKBONE="${RFDIFF_PDBS[0]}"
    cmd '
        mkdir -p /tmp/mpnn_smoke && \
        "$1" "$2"/protein_mpnn_run.py \
            --pdb_path "$3" \
            --out_folder /tmp/mpnn_smoke \
            --num_seq_per_target 2 \
            --sampling_temp 0.1 \
            --batch_size 1 && \
        cat /tmp/mpnn_smoke/seqs/*.fa
    ' "$MPNN_PY" "$MPNN_PATH" "$BACKBONE"
else
    echo "(skipped — ProteinMPNN env or RFdiffusion output missing)"
fi

fi  # SKIP_GPU

# ----------------------------------------------------------------------
step "8. ProteinClaw mock pipeline (no GPU, fast)"
expl "validates the orchestrator + pipeline work end-to-end on this box; if this fails, infra is fine but ProteinClaw isn't"
cmd  "PROTEINCLAW_BACKEND=mock uv run pytest tests/orchestrator/test_orchestrator_integration.py -v"

# ----------------------------------------------------------------------
step "9. ProteinClaw with real backends (slow + costs money/time)"
expl "the real run: ProteinClaw orchestrates the whole pipeline against live tools"
cmd  "uv run pytest -m expensive -v"

printf '\n%sSmoke test done.%s\n' "$BOLD" "$NC"

#!/usr/bin/env bash
# Launch the TREM2 binder run, capped at 4 rounds (strict gate kept at ipSAE>=0.93).
# Wrapped in `sg docker` because the login shell may not yet have the docker group.
set -euo pipefail
cd /home/ubuntu/ProteinClaw
source .venv/bin/activate
exec proteinclaw run \
  "design a binder to TREM2(PDB: 5ELI) that has a sequence that is ≤ 250 amino acids" \
  --output-dir ./runs \
  --rounds 4 \
  2>&1 | tee runs/trem2_rounds4.log

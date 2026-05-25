#!/usr/bin/env bash
set -uo pipefail
WS=/home/ubuntu/.proteinclaw/gpu-workspace/49870fdf95e7
TARGET="AFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQRARLLKDQLSLGNAALQITDVKLQDAGVYRCMISYGGADYKRITVKVNA"
UIDGID="$(id -u):$(id -g)"
python3 - <<'PY' > /tmp/af2_jobs.txt
import json
js=json.load(open("/home/ubuntu/ProteinClaw/runs/49870fdf95e7/scratch/all_seqs.json"))
for k,r in enumerate(js):
    print(f"{k}\t{r['seq']}")
PY
while IFS=$'\t' read -r k seq; do
  cat > "$WS/input.json" <<JSON
{"binder_sequence": "${seq}", "target_sequence": "${TARGET}", "msa_source": "colabfold", "num_recycle": 3, "num_models": 1, "step": ${k}}
JSON
  echo "=== AF2 job $k @ $(date +%H:%M:%S) ==="
  docker run --rm --gpus all -u "$UIDGID" \
    -v "$WS:/workspace" \
    -v ~/.cache/huggingface:/cache/huggingface \
    -v ~/.cache/rfdiffusion:/cache/rfdiffusion \
    -v ~/.cache/proteinmpnn:/cache/proteinmpnn \
    -v ~/.cache/openfold:/cache/openfold \
    -e INPUT_FILE=/workspace/input.json -e OUTPUT_FILE=/workspace/output.json \
    -e SESSION_ID=49870fdf95e7 -e TOOL_NAME=structure.alphafold2_multimer \
    proteinclaw/af2multimer:0.1.0 > "/tmp/af2_$k.log" 2>&1
  echo "  exit=$? @ $(date +%H:%M:%S)"
  cp "$WS/output.json" "$WS/af2_out_${k}.json"
done < /tmp/af2_jobs.txt
echo "ALL_AF2_DONE"

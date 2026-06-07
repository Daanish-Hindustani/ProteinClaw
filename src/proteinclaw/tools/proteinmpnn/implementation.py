"""ProteinMPNN wrapper — runs ``protein_mpnn_run.py`` inside the container.

PRD §9.10 deviations from naive ports:
  * ``sampling_temp`` is a real parameter (not hardcoded 0.1).
  * Subprocess timeout matches ``tool.yaml execution.timeout_s``.
  * ``chain_id`` lets binder workflows keep the target chain frozen.
  * ``normalize_args()`` is separate from ``run()`` so input validation can
    be unit-tested without spinning up PyTorch.
  * VRAM monitor uses the shared ``_gpu_metrics.VramMonitor`` (copied into
    the container by LocalRunner's build-context staging).

Output: a single FASTA in ``/workspace/proteinmpnn_<step>/`` plus the
parsed sequences + scores in the result envelope. PDB bytes never cross
the envelope (PRD §9.3).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Shared VRAM monitor — staged into the build context by LocalRunner.
sys.path.insert(0, "/app")
from _gpu_metrics import VramMonitor, elapsed_s  # type: ignore[import-not-found]
from _normalize import NormalizeError, normalize_args  # type: ignore[import-not-found]


PROTEINMPNN_DIR = "/opt/ProteinMPNN"
WEIGHTS_DIR = "/opt/ProteinMPNN/vanilla_model_weights"
SOLUBLE_WEIGHTS_DIR = "/opt/ProteinMPNN/soluble_model_weights"
WORKSPACE_ROOT = "/workspace"

# ProteinMPNN's FASTA header looks like:
#   >my_pdb, score=1.234, fixed_chains=['A'], designed_chains=['B'], ...
# We parse score and chain breakdown for the envelope.
_HEADER_RE = re.compile(
    r">[^,]+,\s*"
    r"(?:T=(?P<temp>[\d.]+),\s*)?"
    r"sample=(?P<sample>\d+),?\s*"
    r"score=(?P<score>[\d.]+)"
    r"(?:,\s*global_score=(?P<gscore>[\d.]+))?"
    r"(?:,\s*seq_recovery=(?P<recov>[\d.]+))?",
    re.IGNORECASE,
)


def _parse_fasta(fasta_path: Path, *, input_chain_first: bool = True) -> list[dict[str, Any]]:
    """Parse ProteinMPNN output FASTA into a list of design dicts.

    The first record is the input sequence (no score); subsequent records are
    the sampled designs. We skip the first if ``input_chain_first`` is set.
    """
    sequences: list[dict[str, Any]] = []
    headers: list[str] = []
    seqs: list[str] = []
    current_seq: list[str] = []
    current_header: Optional[str] = None

    with fasta_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if current_header is not None:
                    headers.append(current_header)
                    seqs.append("".join(current_seq))
                current_header = line
                current_seq = []
            elif line:
                current_seq.append(line.strip())
        if current_header is not None:
            headers.append(current_header)
            seqs.append("".join(current_seq))

    start = 1 if input_chain_first and len(headers) > 1 else 0
    for header, seq in zip(headers[start:], seqs[start:]):
        m = _HEADER_RE.match(header)
        score = float(m.group("score")) if m else None
        sample = int(m.group("sample")) if m else None
        temp = float(m.group("temp")) if m and m.group("temp") else None
        gscore = float(m.group("gscore")) if m and m.group("gscore") else None
        recov = float(m.group("recov")) if m and m.group("recov") else None
        sequences.append(
            {
                "sequence": seq,
                "score": score,
                "global_score": gscore,
                "seq_recovery": recov,
                "sample": sample,
                "temperature": temp,
                "header": header,
                "length": len(seq.replace("/", "")),
            }
        )
    return sequences


def _build_argv(
    args: dict[str, Any],
    *,
    out_folder: Path,
) -> list[str]:
    # Soluble weights (trained on soluble proteins only) are the literature
    # default for de-novo binder sequence design. The pinned clone ships all
    # four model variants under soluble_model_weights/, so any model_name works.
    weights_dir = SOLUBLE_WEIGHTS_DIR if args.get("use_soluble_model") else WEIGHTS_DIR
    argv: list[str] = [
        sys.executable,
        f"{PROTEINMPNN_DIR}/protein_mpnn_run.py",
        "--pdb_path",
        args["backbone_pdb"],
        "--out_folder",
        str(out_folder),
        "--num_seq_per_target",
        str(args["num_sequences"]),
        "--sampling_temp",
        str(args["sampling_temp"]),
        "--model_name",
        args["model_name"],
        "--path_to_model_weights",
        weights_dir,
        "--batch_size",
        str(args["batch_size"]),
        "--seed",
        str(args["seed"]),
    ]
    if args["chain_id"]:
        argv += ["--pdb_path_chains", args["chain_id"]]
    return argv


def run(**kwargs: Any) -> dict[str, Any]:
    try:
        args = normalize_args(**kwargs)
    except NormalizeError as exc:
        return {
            "summary": f"Error: {exc}",
            "error": "invalid_args",
            "metrics": {},
        }

    step = args["step"]
    out_folder = Path(WORKSPACE_ROOT) / f"proteinmpnn_{step}"
    out_folder.mkdir(parents=True, exist_ok=True)
    seqs_dir = out_folder / "seqs"
    seqs_dir.mkdir(parents=True, exist_ok=True)

    argv = _build_argv(args, out_folder=out_folder)

    t0 = time.monotonic()
    with VramMonitor() as vram:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                # Container-level timeout is enforced by LocalRunner; we
                # leave 30s margin for cleanup.
                timeout=int(os.environ.get("TOOL_TIMEOUT_S", "270")),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "summary": f"Error: ProteinMPNN subprocess timed out: {exc}",
                "error": "subprocess_timeout",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }
        except OSError as exc:
            return {
                "summary": f"Error: could not invoke ProteinMPNN: {exc}",
                "error": "subprocess_failed",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }

    elapsed = elapsed_s(t0)
    metrics = {
        "vram_before_mb": vram.before,
        "vram_peak_mb": vram.peak,
        "elapsed_s": elapsed,
    }

    if proc.returncode != 0:
        return {
            "summary": (
                f"Error: ProteinMPNN exited {proc.returncode}; "
                f"see stderr_tail for details"
            ),
            "error": "subprocess_nonzero",
            "metrics": metrics,
            "details": {
                "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
                "argv": " ".join(shlex.quote(a) for a in argv),
            },
        }

    # ProteinMPNN names the output FASTA after the input PDB stem.
    pdb_stem = Path(args["backbone_pdb"]).stem
    fasta_path = seqs_dir / f"{pdb_stem}.fa"
    if not fasta_path.exists():
        # Fallback: scan for any .fa under seqs/ — sometimes the stem differs.
        candidates = list(seqs_dir.glob("*.fa"))
        if candidates:
            fasta_path = candidates[0]
        else:
            return {
                "summary": "Error: ProteinMPNN ran but produced no output FASTA",
                "error": "missing_output",
                "metrics": metrics,
                "details": {"stdout_tail": (proc.stdout or "")[-2000:]},
            }

    designs = _parse_fasta(fasta_path, input_chain_first=True)
    if not designs:
        return {
            "summary": f"Error: parsed 0 designs from {fasta_path}",
            "error": "empty_output",
            "metrics": metrics,
        }

    sequences = [d["sequence"] for d in designs]
    scores = [d["score"] for d in designs if d["score"] is not None]

    return {
        "summary": (
            f"ProteinMPNN: {len(designs)} sequence(s) (avg score "
            f"{sum(scores) / len(scores):.3f}) → {fasta_path}"
            if scores
            else f"ProteinMPNN: {len(designs)} sequence(s) → {fasta_path}"
        ),
        "fasta_path": str(fasta_path),
        "out_folder": str(out_folder),
        "designs": designs,
        "sequences": sequences,
        "scores": scores,
        "num_designs": len(designs),
        "metrics": metrics,
    }

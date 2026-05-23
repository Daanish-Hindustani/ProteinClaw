"""AF2-multimer wrapper via ColabFold.

PRD §9.10 + Task 5 design choices:
  * Trimmed YAML: only binder_sequence, target_sequence, relax_prediction,
    msa_source — everything else has agent-friendly defaults.
  * MSA path: `colabfold_batch` calls MMseqs2 server. On error / timeout,
    we retry once; on second failure, we re-run with --msa-mode single_sequence
    and stamp `msa_degraded: True` in the envelope.
  * Templates off, relaxation off (unless caller opts in).
  * Output PDB parsing: identifies binder chain by order (binder first → "A")
    and averages B-factors over its CA atoms → `complex_confidence` (PRD §6.6
    "The ranking signal").
  * OpenFold params downloaded by ColabFold on first call into the bind-mounted
    /cache/openfold dir.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, "/app")
from _gpu_metrics import VramMonitor, elapsed_s  # type: ignore[import-not-found]
from _normalize import (  # type: ignore[import-not-found]
    NormalizeError,
    average_chain_plddt,
    normalize_args,
)

WORKSPACE_ROOT = "/workspace"
COLABFOLD_DATA_DIR = "/cache/openfold"


def _jobname(binder: str, target: str) -> str:
    """Per-call unique jobname so multiple AF2 calls in the same step dir
    don't collide and don't trigger ColabFold's "skip when output exists"
    cache. Includes a 10-char hash over the binder+target sequence pair."""
    h = hashlib.sha1(f"{binder}|{target}".encode()).hexdigest()[:10]
    return f"complex_{h}"


def _write_input_fasta(out_dir: Path, binder: str, target: str, name: str) -> Path:
    """Write a 2-chain ColabFold input FASTA. ``:`` separates chain entries."""
    fasta = out_dir / f"{name}.fasta"
    fasta.write_text(f">{name}\n{binder}:{target}\n", encoding="utf-8")
    return fasta


def _build_argv(
    args: dict[str, Any], *, fasta: Path, out_dir: Path, msa_mode: str
) -> list[str]:
    argv: list[str] = [
        "colabfold_batch",
        "--num-recycle",
        str(args["num_recycle"]),
        "--num-models",
        str(args["num_models"]),
        "--model-type",
        "alphafold2_multimer_v3",
        "--data",
        COLABFOLD_DATA_DIR,
        "--rank",
        "multimer",
        "--msa-mode",
        msa_mode,
    ]
    if args["relax_prediction"]:
        argv += ["--amber", "--num-relax", "1"]
    argv += [str(fasta), str(out_dir)]
    return argv


def _find_top_complex_pdb(out_dir: Path, jobname: str) -> Optional[Path]:
    """Locate the rank-1 multimer PDB ColabFold produced for ``jobname``.

    ColabFold names: ``<jobname>_unrelaxed_rank_001_<model>.pdb``
    Relaxed: ``<jobname>_relaxed_rank_001_<model>.pdb``
    """
    relaxed = sorted(out_dir.glob(f"{jobname}_relaxed_rank_001_*.pdb"))
    if relaxed:
        return relaxed[0]
    unrelaxed = sorted(out_dir.glob(f"{jobname}_unrelaxed_rank_001_*.pdb"))
    if unrelaxed:
        return unrelaxed[0]
    fallback = sorted(out_dir.glob(f"{jobname}_*rank_001_*.pdb"))
    return fallback[0] if fallback else None


def _run_colabfold(
    args: dict[str, Any], out_dir: Path, *, msa_mode: str, t0: float, vram: Any
) -> tuple[Optional[Path], Optional[subprocess.CompletedProcess]]:
    """Run colabfold_batch once. Returns ``(rank1_pdb_or_None, proc_or_None)``."""
    jobname = _jobname(args["binder_sequence"], args["target_sequence"])
    fasta = _write_input_fasta(
        out_dir, args["binder_sequence"], args["target_sequence"], jobname
    )
    argv = _build_argv(args, fasta=fasta, out_dir=out_dir, msa_mode=msa_mode)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=int(os.environ.get("TOOL_TIMEOUT_S", "3500")),
            cwd=str(out_dir),
        )
    except subprocess.TimeoutExpired:
        return None, None
    if proc.returncode != 0:
        return None, proc
    return _find_top_complex_pdb(out_dir, jobname), proc


def run(**kwargs: Any) -> dict[str, Any]:
    try:
        args = normalize_args(**kwargs)
    except NormalizeError as exc:
        return {
            "summary": f"Error: {exc}",
            "error": "invalid_args",
            "metrics": {},
        }

    out_folder = Path(WORKSPACE_ROOT) / f"alphafold2_multimer_{args['step']}"
    out_folder.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    msa_degraded = False
    last_proc: Optional[subprocess.CompletedProcess] = None

    with VramMonitor() as vram:
        # Honour explicit single_sequence; otherwise try colabfold MSA twice
        # then fall back. PRD §10.2 deliberate degradation.
        if args["msa_source"] == "single_sequence":
            pdb, last_proc = _run_colabfold(
                args, out_folder, msa_mode="single_sequence", t0=t0, vram=vram
            )
        else:
            pdb, last_proc = _run_colabfold(
                args, out_folder, msa_mode="mmseqs2_uniref_env", t0=t0, vram=vram
            )
            if pdb is None:
                pdb, last_proc = _run_colabfold(
                    args, out_folder, msa_mode="mmseqs2_uniref_env", t0=t0, vram=vram
                )
            if pdb is None:
                msa_degraded = True
                pdb, last_proc = _run_colabfold(
                    args, out_folder, msa_mode="single_sequence", t0=t0, vram=vram
                )

    metrics = {
        "vram_before_mb": vram.before,
        "vram_peak_mb": vram.peak,
        "elapsed_s": elapsed_s(t0),
    }

    if pdb is None:
        return {
            "summary": (
                "Error: ColabFold failed (MSA + single_sequence fallback both did not produce output)"
            ),
            "error": "no_complex_pdb",
            "metrics": metrics,
            "details": {
                "return_code": last_proc.returncode if last_proc else None,
                "stderr_tail": (last_proc.stderr or "")[-2000:] if last_proc else "",
                "stdout_tail": (last_proc.stdout or "")[-2000:] if last_proc else "",
            },
        }

    pdb_text = pdb.read_text(encoding="utf-8", errors="replace")
    binder_chain = "A"  # binder is first in the input FASTA → chain A
    target_chain = "B"
    binder_plddt, n_binder = average_chain_plddt(pdb_text, binder_chain)
    target_plddt, n_target = average_chain_plddt(pdb_text, target_chain)

    if n_binder == 0:
        return {
            "summary": "Error: binder chain not found in ColabFold output PDB",
            "error": "binder_chain_missing",
            "metrics": metrics,
            "details": {"complex_pdb_path": str(pdb)},
        }

    return {
        "summary": (
            f"AF2-multimer: binder-chain pLDDT {binder_plddt:.1f}, target {target_plddt:.1f}"
            + (" (MSA DEGRADED to single-sequence)" if msa_degraded else "")
        ),
        "complex_pdb_path": str(pdb),
        "complex_confidence": round(binder_plddt, 2),  # THE ranking signal
        "binder_chain": binder_chain,
        "target_chain": target_chain,
        "target_chain_plddt": round(target_plddt, 2),
        "num_residues": {
            "binder": n_binder,
            "target": n_target,
        },
        "msa_degraded": msa_degraded,
        "out_folder": str(out_folder),
        "metrics": metrics,
    }

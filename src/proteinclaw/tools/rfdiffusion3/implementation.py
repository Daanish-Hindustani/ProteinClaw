"""RFD3 wrapper — calls ``rfd3 design`` with a generated JSON inputs file.

Builds the inputs JSON dynamically from agent-friendly kwargs:
  * `contig` from binder_length + target chain range.
  * `select_hotspots` from per-residue hotspots with CA/CB defaults.
  * PPI-recommended sampler params (`step_scale=3`, `gamma_0=0.2`,
    `is_non_loopy=true`) applied by default.

Output PDBs land in ``/workspace/rfdiffusion3_<step>/binder/`` (RFD3
creates a subdirectory per spec key). The wrapper globs all .pdb files
and returns them in the envelope.
"""

from __future__ import annotations

import gzip
import json
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
    build_input_spec,
    normalize_args,
)

WORKSPACE_ROOT = "/workspace"
CHECKPOINT_DIR = "/cache/rfdiffusion"
SPEC_NAME = "binder"


def _chain_ca_counts(pdb_text: str) -> dict[str, int]:
    """Count CA atoms per chain in a PDB string."""
    out: dict[str, int] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if " CA " not in line[12:18]:
            continue
        if len(line) < 22:
            continue
        ch = line[21:22]
        out[ch] = out.get(ch, 0) + 1
    return out


def _classify_chains(
    counts: dict[str, int],
    binder_lo: int,
    binder_hi: int,
    target_expected: int,
) -> tuple[Optional[str], Optional[str]]:
    """Decide which chain is the binder and which is the target.

    Heuristic: the binder chain's CA count falls inside ``[binder_lo,
    binder_hi]``; the target chain's CA count is closest to
    ``target_expected``. Returns ``(binder_chain, target_chain)``;
    either can be None if classification is ambiguous.
    """
    if not counts:
        return None, None
    binder_chain: Optional[str] = None
    for ch, n in counts.items():
        if binder_lo <= n <= binder_hi:
            binder_chain = ch
            break
    target_chain: Optional[str] = None
    if target_expected > 0:
        best = None
        for ch, n in counts.items():
            if ch == binder_chain:
                continue
            delta = abs(n - target_expected)
            if best is None or delta < best[0]:
                best = (delta, ch)
        if best is not None and best[0] <= max(5, target_expected // 10):
            target_chain = best[1]
    # Fallback: 2-chain case, assign the leftover.
    if binder_chain and target_chain is None and len(counts) == 2:
        for ch in counts:
            if ch != binder_chain:
                target_chain = ch
    elif target_chain and binder_chain is None and len(counts) == 2:
        for ch in counts:
            if ch != target_chain:
                binder_chain = ch
    return binder_chain, target_chain


def _cif_to_pdb(cif_path: Path) -> Path:
    """Convert a `.cif` or `.cif.gz` (RFD3 output) into a sibling `.pdb`.

    Uses biotite (already in the Foundry slim image). Returns the new path.
    """
    if cif_path.name.endswith(".cif.gz"):
        stem = cif_path.name[: -len(".cif.gz")]
        with gzip.open(cif_path, "rt", encoding="utf-8") as f:
            cif_text = f.read()
    elif cif_path.suffix == ".cif":
        stem = cif_path.stem
        cif_text = cif_path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"unexpected suffix on {cif_path}")

    # biotite path: parse PDBx/mmCIF then write PDB.
    import io
    from biotite.structure.io.pdbx import CIFFile, get_structure
    from biotite.structure.io.pdb import PDBFile

    cif_file = CIFFile.read(io.StringIO(cif_text))
    structure = get_structure(cif_file, model=1)
    pdb_file = PDBFile()
    pdb_file.set_structure(structure)
    out = cif_path.parent / f"{stem}.pdb"
    pdb_file.write(out)
    return out


def _ensure_checkpoint() -> Optional[dict[str, Any]]:
    """Download the RFD3 checkpoint via ``foundry install`` if missing.

    Returns None on success or an error envelope on failure.
    ``foundry install rfd3`` is idempotent — re-running on an installed
    checkpoint is a no-op.
    """
    ckpt_dir = Path(CHECKPOINT_DIR)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # Cheap presence check: if any rfd3* checkpoint exists, skip.
    existing = list(ckpt_dir.glob("rfd3*")) + list(ckpt_dir.glob("**/rfd3*"))
    if existing:
        return None
    try:
        proc = subprocess.run(
            ["foundry", "install", "rfd3", "--checkpoint-dir", str(ckpt_dir)],
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "summary": f"Error: foundry install timed out / failed: {exc}",
            "error": "checkpoint_install_failed",
            "metrics": {},
        }
    if proc.returncode != 0:
        return {
            "summary": "Error: foundry install rfd3 returned non-zero exit",
            "error": "checkpoint_install_failed",
            "metrics": {},
            "details": {
                "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
                "stdout_tail": (proc.stdout or "")[-2000:],
            },
        }
    return None


def _build_argv(
    args: dict[str, Any], *, inputs_path: Path, out_dir: Path
) -> list[str]:
    return [
        "rfd3",
        "design",
        f"out_dir={out_dir}",
        f"inputs={inputs_path}",
        "n_batches=1",
        f"diffusion_batch_size={args['num_designs']}",
        f"inference_sampler.num_timesteps={args['num_timesteps']}",
        f"inference_sampler.step_scale={args['step_scale']}",
        f"inference_sampler.gamma_0={args['gamma_0']}",
        "skip_existing=False",
        "prevalidate_inputs=True",
    ]


def run(**kwargs: Any) -> dict[str, Any]:
    try:
        args = normalize_args(**kwargs)
    except NormalizeError as exc:
        return {
            "summary": f"Error: {exc}",
            "error": "invalid_args",
            "metrics": {},
        }

    ckpt_err = _ensure_checkpoint()
    if ckpt_err is not None:
        return ckpt_err

    out_folder = Path(WORKSPACE_ROOT) / f"rfdiffusion3_{args['step']}"
    out_folder.mkdir(parents=True, exist_ok=True)
    inputs_path = out_folder / "inputs.json"
    inputs_path.write_text(
        json.dumps(build_input_spec(args, spec_name=SPEC_NAME), indent=2),
        encoding="utf-8",
    )

    argv = _build_argv(args, inputs_path=inputs_path, out_dir=out_folder)

    t0 = time.monotonic()
    with VramMonitor() as vram:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=int(os.environ.get("TOOL_TIMEOUT_S", "3500")),
                cwd=str(out_folder),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "summary": f"Error: RFD3 timed out: {exc}",
                "error": "subprocess_timeout",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }
        except OSError as exc:
            return {
                "summary": f"Error: could not invoke rfd3: {exc}",
                "error": "subprocess_failed",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }

    metrics = {
        "vram_before_mb": vram.before,
        "vram_peak_mb": vram.peak,
        "elapsed_s": elapsed_s(t0),
    }

    if proc.returncode != 0:
        return {
            "summary": f"Error: rfd3 exited {proc.returncode}; see stderr_tail.",
            "error": "subprocess_nonzero",
            "metrics": metrics,
            "details": {
                "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
                "stdout_tail": (proc.stdout or "")[-2000:],
                "argv": " ".join(shlex.quote(a) for a in argv),
            },
        }

    # RFD3 outputs are .cif.gz files (atom14 representation). Convert each
    # to a plain .pdb so downstream tools (ProteinMPNN, ESMFold) — which
    # only speak PDB — can read them. Also de-dup by stem to avoid double-
    # counting if both .cif and .cif.gz happen to exist.
    cif_files = sorted(out_folder.rglob("*.cif.gz")) + sorted(out_folder.rglob("*.cif"))
    seen_stems: set[str] = set()
    cif_uniq: list[Path] = []
    for p in cif_files:
        stem = p.name.replace(".cif.gz", "").replace(".cif", "")
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        cif_uniq.append(p)

    if not cif_uniq:
        return {
            "summary": "Error: rfd3 ran but produced no design CIF files",
            "error": "missing_output",
            "metrics": metrics,
            "details": {"stdout_tail": (proc.stdout or "")[-2000:]},
        }

    designs = []
    conv_errors: list[str] = []
    binder_lo, binder_hi = args["binder_length"]
    target_chain = args["target_chain"]
    target_chain_range = args["chain_ranges"].get(target_chain, (0, 0))
    target_expected = target_chain_range[1] - target_chain_range[0] + 1 if target_chain_range != (0, 0) else 0
    overall_binder_chain: Optional[str] = None
    overall_target_chain: Optional[str] = None

    for cif in cif_uniq:
        try:
            pdb_path = _cif_to_pdb(cif)
        except Exception as exc:  # noqa: BLE001
            conv_errors.append(f"{cif.name}: {exc}")
            continue
        text = pdb_path.read_text(encoding="utf-8", errors="replace")
        ca_count = sum(
            1 for line in text.splitlines() if line.startswith("ATOM") and " CA " in line
        )
        # Per-chain CA counts → identify binder (length in declared range)
        # and target (length closest to the input crop length).
        per_chain = _chain_ca_counts(text)
        b_chain, t_chain = _classify_chains(
            per_chain, binder_lo, binder_hi, target_expected
        )
        if overall_binder_chain is None:
            overall_binder_chain = b_chain
            overall_target_chain = t_chain
        designs.append(
            {
                "pdb_path": str(pdb_path),
                "cif_path": str(cif),
                "ca_count": ca_count,
                "chain_ca_counts": per_chain,
                "binder_chain": b_chain,
                "target_chain": t_chain,
            }
        )

    if not designs:
        return {
            "summary": "Error: rfd3 produced CIFs but none could be converted to PDB",
            "error": "cif_conversion_failed",
            "metrics": metrics,
            "details": {"conv_errors": conv_errors[:5]},
        }

    return {
        "summary": (
            f"RFD3: {len(designs)} backbone(s) generated; "
            f"in output PDBs the BINDER is chain "
            f"{overall_binder_chain or '?'} and the TARGET is chain "
            f"{overall_target_chain or '?'} "
            f"({len(args['hotspot_residues'])} hotspots, "
            f"binder length {args['binder_length'][0]}-{args['binder_length'][1]})"
        ),
        "designs": designs,
        "design_paths": [d["pdb_path"] for d in designs],
        "out_folder": str(out_folder),
        "num_designs": len(designs),
        "input_target_chain": args["target_chain"],
        "output_binder_chain": overall_binder_chain,
        "output_target_chain": overall_target_chain,
        "hotspot_residues": args["hotspot_residues"],
        "select_hotspots": args["select_hotspots"],
        "metrics": metrics,
    }

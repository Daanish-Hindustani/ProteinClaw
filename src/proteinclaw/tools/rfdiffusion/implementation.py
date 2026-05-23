"""RFdiffusion wrapper — wraps ``scripts/run_inference.py``.

PRD §9.10 deviations + Phase 4 design choices:
  * Lazy weight download from the IPD HTTP mirror on first call. Magic-byte
    check (``PK\\x03\\x04`` ZIP or ``\\x80`` pickle) before reusing a cached
    file, so a half-downloaded checkpoint doesn't silently corrupt runs.
  * Hotspot string is parsed + chain-validated in ``_normalize.py`` (testable
    on the host without GPU).
  * Output PDBs are **not** truncated — full backbone PDBs land in
    ``/workspace/rfdiffusion_<step>/`` and only paths cross the envelope.
  * VRAM monitor + elapsed timing via the shared ``_gpu_metrics`` module.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, "/app")
from _gpu_metrics import VramMonitor, elapsed_s  # type: ignore[import-not-found]
from _normalize import NormalizeError, normalize_args  # type: ignore[import-not-found]

WORKSPACE_ROOT = "/workspace"
RFDIFFUSION_DIR = "/app/RFdiffusion"
WEIGHTS_DIR = Path("/cache/rfdiffusion")

# Canonical RFdiffusion v1 checkpoints (RosettaCommons/RFdiffusion). The
# Complex variant is the binder-trained one; Base is the general model.
# Other checkpoints (InpaintSeq, ActiveSite, etc.) are not lazy-downloaded
# here — uncommon configs can wget them once into the cache manually.
WEIGHT_URLS = {
    "Base_ckpt.pt": (
        "http://files.ipd.uw.edu/pub/RFdiffusion/"
        "6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt"
    ),
    "Complex_base_ckpt.pt": (
        "http://files.ipd.uw.edu/pub/RFdiffusion/"
        "e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt"
    ),
}

# PyTorch checkpoint magic bytes — ZIP format (torch >= 1.6) or legacy pickle.
_TORCH_MAGIC_PREFIXES = (b"PK\x03\x04", b"\x80")


def _verify_torch_checkpoint(path: Path) -> bool:
    """Cheap sanity check that ``path`` looks like a PyTorch checkpoint."""
    try:
        with path.open("rb") as f:
            head = f.read(4)
    except OSError:
        return False
    return any(head.startswith(prefix) for prefix in _TORCH_MAGIC_PREFIXES)


def _ensure_weights(use_complex: bool) -> Optional[dict[str, Any]]:
    """Download missing required weights into ``WEIGHTS_DIR``.

    Returns ``None`` on success or an error envelope on failure.
    """
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    required = ["Complex_base_ckpt.pt"] if use_complex else ["Base_ckpt.pt"]
    for name in required:
        dst = WEIGHTS_DIR / name
        if dst.exists() and dst.stat().st_size > 0:
            if _verify_torch_checkpoint(dst):
                continue
            # Stale / corrupted — re-download.
            try:
                dst.unlink()
            except OSError:
                pass
        url = WEIGHT_URLS[name]
        try:
            urllib.request.urlretrieve(url, dst)  # noqa: S310 — pinned URL
        except Exception as exc:  # noqa: BLE001
            return {
                "summary": f"Error: weight download failed for {name}: {exc}",
                "error": "weight_download_failed",
                "metrics": {},
            }
        if not _verify_torch_checkpoint(dst):
            try:
                dst.unlink()
            except OSError:
                pass
            return {
                "summary": (
                    f"Error: downloaded {name} failed magic-byte check "
                    f"(not a PyTorch checkpoint)"
                ),
                "error": "weight_corrupt",
                "metrics": {},
            }
    return None


def _contigs_for_binder(
    target_chain: str,
    chain_range: tuple[int, int],
    binder_length: tuple[int, int],
) -> str:
    """Build a Hydra ``contigmap.contigs`` string for a binder run.

    Result is ``[<target_chain><min>-<max>/0 <bl_lo>-<bl_hi>]`` — the
    inline-list form RFdiffusion's CLI expects.
    """
    lo, hi = binder_length
    return f"[{target_chain}{chain_range[0]}-{chain_range[1]}/0 {lo}-{hi}]"


def _hotspots_for_cli(hotspots: list[str]) -> str:
    return "[" + ",".join(hotspots) + "]"


def _build_argv(
    args: dict[str, Any], *, output_prefix: Path
) -> list[str]:
    if not args["chain_ranges"]:
        raise RuntimeError(
            "normalize_args did not populate chain_ranges — internal bug; "
            "ensure the PDB is readable inside the container."
        )
    chain_range = args["chain_ranges"][args["target_chain"]]
    contigs = _contigs_for_binder(
        args["target_chain"], chain_range, args["binder_length"]
    )
    hotspots = _hotspots_for_cli(args["hotspot_residues"])
    ckpt_name = "Complex_base_ckpt.pt" if args["use_complex_weights"] else "Base_ckpt.pt"
    # Disable Hydra's automatic outputs/ directory (we don't need its logs and
    # writing into /app/RFdiffusion would fail under our UID-1000 container).
    hydra_overrides = [
        "hydra.run.dir=.",
        "hydra.output_subdir=null",
        "hydra.job_logging.handlers.file.filename=/dev/null",
    ]
    argv: list[str] = [
        sys.executable,
        f"{RFDIFFUSION_DIR}/scripts/run_inference.py",
        f"inference.input_pdb={args['target_pdb']}",
        f"inference.output_prefix={output_prefix}",
        f"inference.num_designs={args['num_designs']}",
        f"inference.model_directory_path={WEIGHTS_DIR}",
        f"inference.ckpt_override_path={WEIGHTS_DIR / ckpt_name}",
        f"contigmap.contigs={contigs}",
        f"ppi.hotspot_res={hotspots}",
        f"diffuser.T={args['diffuser_T']}",
        *hydra_overrides,
    ]
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

    weight_err = _ensure_weights(args["use_complex_weights"])
    if weight_err is not None:
        return weight_err

    out_folder = Path(WORKSPACE_ROOT) / f"rfdiffusion_{args['step']}"
    out_folder.mkdir(parents=True, exist_ok=True)
    output_prefix = out_folder / "design"

    try:
        argv = _build_argv(args, output_prefix=output_prefix)
    except RuntimeError as exc:
        return {
            "summary": f"Error: {exc}",
            "error": "internal_error",
            "metrics": {},
        }

    t0 = time.monotonic()
    with VramMonitor() as vram:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=int(os.environ.get("TOOL_TIMEOUT_S", "1700")),
                # Run from the writable session workspace so any Hydra
                # leftover files land somewhere we own.
                cwd=str(out_folder),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "summary": f"Error: RFdiffusion timed out: {exc}",
                "error": "subprocess_timeout",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }
        except OSError as exc:
            return {
                "summary": f"Error: could not invoke RFdiffusion: {exc}",
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
            "summary": (
                f"Error: RFdiffusion exited {proc.returncode}; see stderr_tail."
            ),
            "error": "subprocess_nonzero",
            "metrics": metrics,
            "details": {
                "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2000:],
                "stdout_tail": (proc.stdout or "")[-2000:],
                "argv": " ".join(shlex.quote(a) for a in argv),
            },
        }

    design_pdbs = sorted(out_folder.glob("design_*.pdb"))
    if not design_pdbs:
        return {
            "summary": "Error: RFdiffusion ran but produced no design PDBs",
            "error": "missing_output",
            "metrics": metrics,
            "details": {"stdout_tail": (proc.stdout or "")[-2000:]},
        }

    designs = []
    for p in design_pdbs:
        ca_count = sum(
            1
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("ATOM") and " CA " in line
        )
        designs.append({
            "pdb_path": str(p),
            "ca_count": ca_count,
        })

    return {
        "summary": (
            f"RFdiffusion: {len(designs)} backbone(s) generated "
            f"(target_chain={args['target_chain']}, {len(args['hotspot_residues'])} hotspots, "
            f"binder length {args['binder_length'][0]}-{args['binder_length'][1]})"
        ),
        "designs": designs,
        "design_paths": [d["pdb_path"] for d in designs],
        "out_folder": str(out_folder),
        "num_designs": len(designs),
        "target_chain": args["target_chain"],
        "hotspot_residues": args["hotspot_residues"],
        "metrics": metrics,
    }

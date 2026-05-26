"""RFantibody wrapper — three-stage de novo nanobody / scFv CDR design.

Runs the full RFantibody pipeline inside a single container call:
  Stage 1 — rfdiffusion (Ab-finetuned): CDR backbone generation from a
            fixed VHH or scFv framework scaffold → Quiver file.
  Stage 2 — proteinmpnn (CDR-only): sequence design on each backbone
            → sequenced Quiver file.
  Stage 3 — rf2 (Ab-finetuned): self-consistency structure prediction
            + pAE / RMSD scoring → scored Quiver file.

Post-processing:
  - Extract PDB files from the scored Quiver via qvextract.
  - Parse scores from qvscorefile TSV output.
  - Apply RF2 self-consistency filter (pAE < threshold AND RMSD < threshold).
  - Rename chains: H → A (VHH/binder), T → B (target), L → A (scFv light
    chain merges into A) so downstream ProteinClaw tools (AF2-multimer) see
    the standard chain layout.

Weight download is lazy (first call only) and cached in /cache/rfantibody.
"""

from __future__ import annotations

import csv
import io
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
    build_hotspot_arg,
    build_loop_lengths_arg,
    normalize_args,
)

WORKSPACE_ROOT = "/workspace"
RFANTIBODY_HOME = Path(os.environ.get("RFANTIBODY_HOME", "/app/rfantibody"))
WEIGHTS_DIR = Path(os.environ.get("RFANTIBODY_WEIGHTS", "/cache/rfantibody"))

# Bundled example framework PDBs shipped with RFantibody
_FRAMEWORK_PDBS: dict[str, Path] = {
    "vhh": RFANTIBODY_HOME / "scripts/examples/example_inputs/h-NbBCII10.pdb",
    "scfv": RFANTIBODY_HOME / "scripts/examples/example_inputs/hu-4D5-8_Fv.pdb",
}

# HLT chain → ProteinClaw standard chain.
# H = heavy chain (VHH binder or Fv heavy) → A
# L = light chain (Fv light, absent in VHH) → A  (becomes part of the binder)
# T = target antigen → B
_CHAIN_REMAP = {"H": "A", "L": "A", "T": "B"}


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: Optional[dict[str, str]] = None,
) -> tuple[int, str, str]:
    """Run a subprocess, returning (returncode, stdout, stderr)."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        cwd=str(cwd),
        env=env,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _base_metrics(vram: Any, t0: float) -> dict[str, Any]:
    return {
        "vram_before_mb": vram.before,
        "vram_peak_mb": vram.peak,
        "elapsed_s": elapsed_s(t0),
    }


def _timeout_env(stage: str, vram: Any, t0: float) -> dict[str, Any]:
    return {
        "summary": f"Error: {stage} timed out",
        "error": "subprocess_timeout",
        "metrics": _base_metrics(vram, t0),
    }


def _oserr_env(stage: str, exc: OSError, vram: Any, t0: float) -> dict[str, Any]:
    return {
        "summary": f"Error: could not invoke {stage}: {exc}",
        "error": "subprocess_failed",
        "metrics": _base_metrics(vram, t0),
    }


def _nonzero_env(
    stage: str,
    rc: int,
    stdout: str,
    stderr: str,
    argv: list[str],
    vram: Any,
    t0: float,
) -> dict[str, Any]:
    return {
        "summary": f"Error: {stage} exited {rc}; see stderr_tail.",
        "error": "subprocess_nonzero",
        "metrics": _base_metrics(vram, t0),
        "details": {
            "stage": stage,
            "return_code": rc,
            "stderr_tail": stderr[-2000:],
            "stdout_tail": stdout[-2000:],
            "argv": " ".join(shlex.quote(a) for a in argv),
        },
    }


# ---------------------------------------------------------------------------
# Weight management
# ---------------------------------------------------------------------------

def _ensure_weights() -> Optional[dict[str, Any]]:
    """Download RFantibody model weights on first call; idempotent.

    The download script (include/download_weights.sh) is run with
    RFANTIBODY_WEIGHTS set to the bind-mounted /cache/rfantibody.
    Subsequent calls skip download if any .pt/.pth weights are present.
    """
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    # Presence check: any .pt or .pth file anywhere under the weights dir
    # or the rfantibody home (some scripts put weights in-tree).
    existing = (
        list(WEIGHTS_DIR.rglob("*.pt"))
        + list(WEIGHTS_DIR.rglob("*.pth"))
        + list((RFANTIBODY_HOME / "weights").rglob("*.pt"))
        if (RFANTIBODY_HOME / "weights").exists()
        else []
    )
    if existing:
        return None

    script = RFANTIBODY_HOME / "include" / "download_weights.sh"
    if not script.exists():
        return {
            "summary": (
                f"Error: RFantibody weight download script not found at {script}. "
                "Ensure the Docker image was built with the full RFantibody repo."
            ),
            "error": "weights_missing",
            "metrics": {},
        }

    env = dict(os.environ)
    env["RFANTIBODY_WEIGHTS"] = str(WEIGHTS_DIR)

    try:
        rc, stdout, stderr = _run(
            ["bash", str(script)],
            cwd=RFANTIBODY_HOME,
            timeout=1800,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "summary": "Error: RFantibody weight download timed out (30 min limit)",
            "error": "weights_download_timeout",
            "metrics": {},
        }

    if rc != 0:
        return {
            "summary": f"Error: RFantibody weight download failed (exit {rc})",
            "error": "weights_download_failed",
            "metrics": {},
            "details": {
                "stderr_tail": stderr[-2000:],
                "stdout_tail": stdout[-2000:],
            },
        }
    return None


# ---------------------------------------------------------------------------
# PDB post-processing
# ---------------------------------------------------------------------------

def _rename_chains(pdb_text: str, remap: dict[str, str]) -> str:
    """Rename chain IDs in ATOM / HETATM / TER records."""
    lines: list[str] = []
    for line in pdb_text.splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM", "TER   ", "TER\n", "TER\r")):
            if len(line) > 21:
                old = line[21]
                new = remap.get(old, old)
                line = line[:21] + new + line[22:]
        lines.append(line)
    return "".join(lines)


def _extract_sequence_from_chain(pdb_text: str, chain: str = "H") -> str:
    """Return single-letter sequence from CA ATOM records on *chain*."""
    _3to1 = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    residues: list[tuple[int, str]] = []
    seen: set[int] = set()
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or len(line) < 26:
            continue
        if line[12:16].strip() != "CA":
            continue
        if line[21] != chain:
            continue
        try:
            resi = int(line[22:26].strip())
        except ValueError:
            continue
        if resi in seen:
            continue
        seen.add(resi)
        resn = line[17:20].strip().upper()
        residues.append((resi, _3to1.get(resn, "X")))
    residues.sort(key=lambda x: x[0])
    return "".join(aa for _, aa in residues)


# ---------------------------------------------------------------------------
# Quiver score parsing
# ---------------------------------------------------------------------------

def _parse_qv_scores(tsv_text: str) -> dict[str, dict[str, float]]:
    """Parse ``qvscorefile`` TSV output → ``{design_name: {metric: value}}``."""
    result: dict[str, dict[str, float]] = {}
    try:
        reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
        for row in reader:
            # qvscorefile uses "tag" or "description" as the design identifier
            name = row.get("tag") or row.get("description") or row.get("name", "")
            if not name:
                continue
            scores: dict[str, float] = {}
            for k, v in row.items():
                if k in ("tag", "description", "name"):
                    continue
                try:
                    scores[k] = float(v)
                except (TypeError, ValueError):
                    pass
            result[name] = scores
    except Exception:  # noqa: BLE001
        pass
    return result


def _get_pae_rmsd(scores: dict[str, float]) -> tuple[Optional[float], Optional[float]]:
    """Extract pAE and RMSD from a score dict; handles varied column names."""
    pae: Optional[float] = None
    rmsd: Optional[float] = None
    for k, v in scores.items():
        kl = k.lower()
        if pae is None and "pae" in kl:
            pae = v
        if rmsd is None and "rmsd" in kl:
            rmsd = v
    return pae, rmsd


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(**kwargs: Any) -> dict[str, Any]:
    # --- validate inputs ---
    try:
        args = normalize_args(**kwargs)
    except NormalizeError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}

    # --- weights ---
    w_err = _ensure_weights()
    if w_err is not None:
        return w_err

    # --- output directory layout ---
    out_dir = Path(WORKSPACE_ROOT) / f"rfantibody_{args['step']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    designs_dir = out_dir / "designs"
    designs_dir.mkdir(exist_ok=True)

    qv1 = out_dir / "1_rfdiffusion.qv"
    qv2 = out_dir / "2_proteinmpnn.qv"
    qv3 = out_dir / "3_rf2.qv"

    # --- framework PDB ---
    if args["framework_pdb"]:
        framework_path = Path(args["framework_pdb"])
    else:
        framework_path = _FRAMEWORK_PDBS.get(args["framework_type"])
        if framework_path is None or not framework_path.exists():
            return {
                "summary": (
                    f"Error: bundled {args['framework_type'].upper()} framework PDB "
                    f"not found at {framework_path}. "
                    "Ensure the Docker image was built from the full RFantibody repo."
                ),
                "error": "framework_missing",
                "metrics": {},
            }

    # --- build CLI argument lists ---
    hotspot_str = build_hotspot_arg(args["hotspot_residues"])
    loop_str = build_loop_lengths_arg(args["loop_lengths"])

    rfd_argv = [
        "rfdiffusion",
        "-t", args["target_pdb"],
        "-f", str(framework_path),
        "-q", str(qv1),
        "-n", str(args["num_designs"]),
        "-h", hotspot_str,
    ]
    if loop_str:
        rfd_argv += ["-l", loop_str]

    mpnn_argv = [
        "proteinmpnn",
        "-q", str(qv1),
        "--output-quiver", str(qv2),
        "-n", str(args["seqs_per_struct"]),
        "-t", str(args["temperature"]),
    ]

    rf2_argv = [
        "rf2",
        "-q", str(qv2),
        "--output-quiver", str(qv3),
        "-r", str(args["num_recycles"]),
    ]

    t0 = time.monotonic()

    with VramMonitor() as vram:
        # Stage 1 — RFdiffusion
        try:
            rc, stdout, stderr = _run(rfd_argv, cwd=out_dir, timeout=3600)
        except subprocess.TimeoutExpired:
            return _timeout_env("rfdiffusion", vram, t0)
        except OSError as exc:
            return _oserr_env("rfdiffusion", exc, vram, t0)
        if rc != 0:
            return _nonzero_env("rfdiffusion", rc, stdout, stderr, rfd_argv, vram, t0)

        # Stage 2 — ProteinMPNN
        try:
            rc, stdout, stderr = _run(mpnn_argv, cwd=out_dir, timeout=1800)
        except subprocess.TimeoutExpired:
            return _timeout_env("proteinmpnn", vram, t0)
        except OSError as exc:
            return _oserr_env("proteinmpnn", exc, vram, t0)
        if rc != 0:
            return _nonzero_env("proteinmpnn", rc, stdout, stderr, mpnn_argv, vram, t0)

        # Stage 3 — RF2
        try:
            rc, stdout, stderr = _run(rf2_argv, cwd=out_dir, timeout=3600)
        except subprocess.TimeoutExpired:
            return _timeout_env("rf2", vram, t0)
        except OSError as exc:
            return _oserr_env("rf2", exc, vram, t0)
        if rc != 0:
            return _nonzero_env("rf2", rc, stdout, stderr, rf2_argv, vram, t0)

    metrics = {
        "vram_before_mb": vram.before,
        "vram_peak_mb": vram.peak,
        "elapsed_s": elapsed_s(t0),
    }

    # --- extract scores from the final Quiver file ---
    try:
        rc_sc, score_tsv, _ = _run(
            ["qvscorefile", str(qv3)], cwd=out_dir, timeout=120
        )
        all_scores = _parse_qv_scores(score_tsv) if rc_sc == 0 else {}
    except Exception:  # noqa: BLE001
        all_scores = {}

    # --- extract PDB files ---
    try:
        _run(["qvextract", str(qv3)], cwd=designs_dir, timeout=300)
    except Exception:  # noqa: BLE001
        pass  # best-effort; continue with whatever files appeared

    raw_pdbs = sorted(designs_dir.glob("*.pdb"))
    if not raw_pdbs:
        return {
            "summary": (
                "Error: RFantibody pipeline completed but no design PDB files "
                "were extracted from the Quiver output"
            ),
            "error": "missing_output",
            "metrics": metrics,
        }

    # --- per-design post-processing: filter + rename chains + extract seq ---
    designs: list[dict[str, Any]] = []
    for pdb_path in raw_pdbs:
        name = pdb_path.stem
        scores = all_scores.get(name, {})
        pae, rmsd = _get_pae_rmsd(scores)

        passes = (pae is None or pae < args["pae_threshold"]) and (
            rmsd is None or rmsd < args["rmsd_threshold"]
        )

        try:
            raw_text = pdb_path.read_text(encoding="utf-8", errors="replace")
            renamed_text = _rename_chains(raw_text, _CHAIN_REMAP)
            sequence = _extract_sequence_from_chain(raw_text, chain="H")
            # Write renamed PDB alongside the original
            renamed_path = designs_dir / f"renamed_{pdb_path.name}"
            renamed_path.write_text(renamed_text, encoding="utf-8")
            out_pdb = str(renamed_path)
        except Exception as exc:  # noqa: BLE001
            out_pdb = str(pdb_path)
            sequence = ""
            passes = False
            scores["_rename_error"] = str(exc)

        designs.append(
            {
                "pdb_path": out_pdb,
                "original_pdb_path": str(pdb_path),
                "name": name,
                "sequence": sequence,
                "rf2_pae": pae,
                "rf2_rmsd": rmsd,
                "passes_filter": passes,
                "binder_chain": "A",
                "target_chain": "B",
                "rf2_scores": scores,
            }
        )

    filtered = [d for d in designs if d["passes_filter"]]
    n_total = len(designs)
    n_filtered = len(filtered)

    return {
        "summary": (
            f"RFantibody: {n_total} design(s) generated; "
            f"{n_filtered} pass RF2 self-consistency filter "
            f"(pAE<{args['pae_threshold']}, RMSD<{args['rmsd_threshold']}Å). "
            f"Framework: {args['framework_type'].upper()}, "
            f"hotspots: {hotspot_str}"
        ),
        "designs": designs,
        "design_paths": [d["pdb_path"] for d in designs],
        "filtered_design_paths": [d["pdb_path"] for d in filtered],
        "filtered_designs": filtered,
        "num_designs": n_total,
        "num_filtered": n_filtered,
        "out_folder": str(out_dir),
        "framework_type": args["framework_type"],
        "hotspot_residues": args["hotspot_residues"],
        "metrics": metrics,
        "session_id": args["session_id"],
    }

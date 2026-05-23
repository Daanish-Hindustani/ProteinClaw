"""ESMFold wrapper — monomer structure prediction.

PRD §9.10 deviations:
  * Model load hoisted to module scope. ``_MODEL`` and ``_TOKENIZER`` are
    initialised on first call and cached for the container's lifetime, so
    a batch of N sequences pays the load cost exactly once.
  * Batch mode: one call processes ``sequences: List[str]``.
  * No silent fallback — if torch/transformers can't be imported, return
    ``{"error": "esmfold_libraries_missing"}`` instead of pretending to fold.
  * Enforce ``MAX_LEN=1024`` in ``_normalize.normalize_args``.

Output: one PDB per sequence in ``/workspace/esmfold_<step>/<i>_<short>.pdb``,
plus per-sequence pLDDT (0-100 scale, mean over residues × atoms).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, "/app")
from _gpu_metrics import VramMonitor, elapsed_s  # type: ignore[import-not-found]
from _normalize import NormalizeError, normalize_args  # type: ignore[import-not-found]


WORKSPACE_ROOT = "/workspace"
_MODEL: Any = None
_TOKENIZER: Any = None
_LOAD_COUNT = 0


def _libs_available() -> Optional[str]:
    """Return None if torch/transformers import cleanly, else error string."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — explicit no-fallback
        return f"{type(exc).__name__}: {exc}"
    return None


def _load_model(chunk_size: int = 64) -> None:
    """Load ESMFold + tokenizer once into module scope. No-op on second call."""
    global _MODEL, _TOKENIZER, _LOAD_COUNT
    if _MODEL is not None and _TOKENIZER is not None:
        return
    import torch
    from transformers import AutoTokenizer, EsmForProteinFolding

    _TOKENIZER = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    model = EsmForProteinFolding.from_pretrained(
        "facebook/esmfold_v1",
        low_cpu_mem_usage=True,
    )
    model = model.eval().cuda()
    # ESMFold's ESM submodule needs fp32 for numerical stability; the trunk
    # can run mixed-precision. This is the standard pattern from HF docs.
    model.esm = model.esm.float()
    model.trunk.set_chunk_size(chunk_size)
    _MODEL = model
    _LOAD_COUNT += 1


def _fold_one(sequence: str) -> dict[str, Any]:
    """Fold one sequence. Returns dict with pdb_text, plddt, per_residue_plddt."""
    import torch

    tokens = _TOKENIZER(
        [sequence],
        return_tensors="pt",
        padding=False,
        add_special_tokens=False,
    )["input_ids"].cuda()

    with torch.no_grad():
        output = _MODEL(tokens)

    # `output_to_pdb` returns a list of PDB strings (one per batch item).
    pdb_texts = _MODEL.output_to_pdb(output)
    pdb_text = pdb_texts[0]

    # output.plddt shape: (batch=1, seq_len, 37 atoms). Range is 0-1; scale to 0-100.
    plddt_tensor = output.plddt[0]  # (seq_len, 37)
    per_residue = plddt_tensor.mean(dim=-1).cpu().numpy()  # (seq_len,)
    mean_plddt = float(per_residue.mean()) * 100.0

    return {
        "pdb_text": pdb_text,
        "confidence": mean_plddt,
        "per_residue_plddt": [float(x) * 100.0 for x in per_residue.tolist()],
        "num_residues": len(sequence),
    }


def run(**kwargs: Any) -> dict[str, Any]:
    try:
        args = normalize_args(**kwargs)
    except NormalizeError as exc:
        return {
            "summary": f"Error: {exc}",
            "error": "invalid_args",
            "metrics": {},
        }

    missing = _libs_available()
    if missing is not None:
        return {
            "summary": f"Error: ESMFold libraries missing — {missing}",
            "error": "esmfold_libraries_missing",
            "metrics": {},
        }

    out_folder = Path(WORKSPACE_ROOT) / f"esmfold_{args['step']}"
    out_folder.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    with VramMonitor() as vram:
        try:
            _load_model(chunk_size=args["chunk_size"])
        except Exception as exc:  # noqa: BLE001
            return {
                "summary": f"Error: failed to load ESMFold checkpoint — {exc}",
                "error": "model_load_failed",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                },
            }
        load_elapsed = elapsed_s(t0)
        load_count_at_call = _LOAD_COUNT

        predictions: list[dict[str, Any]] = []
        try:
            for i, seq in enumerate(args["sequences"]):
                result = _fold_one(seq)
                # Write PDB; filename uses index + first 8 residues for sanity.
                short = seq[:8] if len(seq) >= 8 else seq
                pdb_path = out_folder / f"{i:03d}_{short}.pdb"
                pdb_path.write_text(result.pop("pdb_text"), encoding="utf-8")
                predictions.append(
                    {
                        "index": i,
                        "sequence": seq,
                        "pdb_path": str(pdb_path),
                        "confidence": round(result["confidence"], 2),
                        "per_residue_plddt": [
                            round(x, 2) for x in result["per_residue_plddt"]
                        ],
                        "num_residues": result["num_residues"],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            return {
                "summary": f"Error: ESMFold inference failed at sequence {len(predictions)}: {exc}",
                "error": "inference_failed",
                "metrics": {
                    "vram_before_mb": vram.before,
                    "vram_peak_mb": vram.peak,
                    "elapsed_s": elapsed_s(t0),
                    "model_load_count": load_count_at_call,
                },
                "predictions": predictions,
            }

    total_elapsed = elapsed_s(t0)
    confidences = [p["confidence"] for p in predictions]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "summary": (
            f"ESMFold: {len(predictions)} structure(s); mean pLDDT "
            f"{avg_conf:.1f} (range {min(confidences):.1f}-{max(confidences):.1f})"
            if confidences
            else f"ESMFold: {len(predictions)} structure(s)"
        ),
        "predictions": predictions,
        "out_folder": str(out_folder),
        "num_predictions": len(predictions),
        "metrics": {
            "vram_before_mb": vram.before,
            "vram_peak_mb": vram.peak,
            "elapsed_s": total_elapsed,
            "model_load_elapsed_s": load_elapsed,
            # If 1, this container loaded the model (cold start); >1 means
            # the module-scope cache was hit (would only happen if the same
            # container processed multiple `run()` calls, which we don't do).
            "model_load_count": load_count_at_call,
        },
    }

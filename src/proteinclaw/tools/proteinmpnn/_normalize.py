"""Pure input validation for ProteinMPNN — host-importable for unit tests.

Kept separate from ``implementation.py`` so tests can call ``normalize_args``
without triggering the container-only imports (``_gpu_metrics``, etc).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

WORKSPACE_ROOT = "/workspace"
ALLOWED_MODELS = {"v_48_002", "v_48_010", "v_48_020", "v_48_030"}
_CHAIN_RE = re.compile(r"^[A-Za-z]$")


class NormalizeError(ValueError):
    """Raised when input arguments are invalid."""


def normalize_args(
    *,
    backbone_pdb: str,
    num_sequences: int = 8,
    sampling_temp: float = 0.1,
    chain_id: Optional[str] = None,
    model_name: str = "v_48_020",
    seed: int = 0,
    batch_size: int = 1,
    step: int = 0,
    session_id: str = "",
    workspace_root: str = WORKSPACE_ROOT,
    skip_path_check: bool = False,
) -> dict[str, Any]:
    """Validate and normalise kwargs for ``run()``.

    Setting ``skip_path_check=True`` bypasses the ``/workspace`` containment
    + existence check — useful for tests that want to exercise the rest of
    the validation logic without staging a real file.
    """
    if not isinstance(num_sequences, int) or not 1 <= num_sequences <= 64:
        raise NormalizeError(f"num_sequences must be 1..64, got {num_sequences!r}")
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 32:
        raise NormalizeError(f"batch_size must be 1..32, got {batch_size!r}")
    try:
        st = float(sampling_temp)
    except (TypeError, ValueError):
        raise NormalizeError(f"sampling_temp must be numeric, got {sampling_temp!r}")
    if not 0.01 <= st <= 1.0:
        raise NormalizeError(f"sampling_temp must be 0.01..1.0, got {sampling_temp!r}")
    if chain_id is not None and not _CHAIN_RE.match(chain_id):
        raise NormalizeError(f"chain_id must be a single letter, got {chain_id!r}")
    if model_name not in ALLOWED_MODELS:
        raise NormalizeError(
            f"unknown model_name {model_name!r}; expected one of {sorted(ALLOWED_MODELS)}"
        )
    if not isinstance(seed, int) or seed < 0:
        raise NormalizeError(f"seed must be a non-negative int, got {seed!r}")
    if not backbone_pdb:
        raise NormalizeError("backbone_pdb is required")

    backbone = Path(backbone_pdb)
    if not backbone.is_absolute():
        backbone = Path(workspace_root) / backbone

    if not skip_path_check:
        ws_prefix = workspace_root.rstrip("/") + "/"
        if not str(backbone).startswith(ws_prefix) and str(backbone) != workspace_root:
            raise NormalizeError(
                f"backbone_pdb must live under {workspace_root}/, got {backbone}"
            )
        if not backbone.exists():
            raise NormalizeError(f"backbone PDB not found: {backbone}")
        if backbone.suffix.lower() != ".pdb":
            raise NormalizeError(f"backbone must be a .pdb file, got {backbone.name}")

    return {
        "backbone_pdb": str(backbone),
        "num_sequences": num_sequences,
        "sampling_temp": st,
        "chain_id": chain_id,
        "model_name": model_name,
        "seed": seed,
        "batch_size": batch_size,
        "step": int(step),
        "session_id": session_id,
    }


__all__ = ["NormalizeError", "normalize_args", "WORKSPACE_ROOT", "ALLOWED_MODELS"]

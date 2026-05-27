"""Pure input validation for ESMFold — host-importable."""

from __future__ import annotations

import re
from typing import Any, Optional

VALID_AAS = set("ACDEFGHIKLMNPQRSTVWY")
MAX_LEN = 1024
MAX_BATCH = 64

_NON_AA_RE = re.compile(r"[^ACDEFGHIKLMNPQRSTVWY]")


class NormalizeError(ValueError):
    """Raised when input arguments are invalid."""


def normalize_args(
    *,
    sequences: list,
    step: int = 0,
    session_id: str = "",
    chunk_size: int = 64,
) -> dict[str, Any]:
    """Validate batch of sequences. Returns normalised dict."""
    if not isinstance(sequences, list) or not sequences:
        raise NormalizeError("sequences must be a non-empty list")
    if len(sequences) > MAX_BATCH:
        raise NormalizeError(
            f"batch too large: {len(sequences)} > {MAX_BATCH}"
        )
    cleaned: list[str] = []
    for i, raw in enumerate(sequences):
        if not isinstance(raw, str) or not raw:
            raise NormalizeError(f"sequence #{i} is not a non-empty string")
        s = raw.strip().upper()
        if len(s) > MAX_LEN:
            raise NormalizeError(
                f"sequence #{i} length {len(s)} exceeds MAX_LEN={MAX_LEN}"
            )
        bad = _NON_AA_RE.search(s)
        if bad:
            raise NormalizeError(
                f"sequence #{i} contains non-standard residue {bad.group()!r}"
            )
        cleaned.append(s)
    if not isinstance(chunk_size, int) or not 16 <= chunk_size <= 256:
        raise NormalizeError(f"chunk_size must be 16..256, got {chunk_size!r}")
    if not isinstance(step, int) or step < 0:
        raise NormalizeError(f"step must be >= 0, got {step!r}")
    return {
        "sequences": cleaned,
        "step": step,
        "session_id": session_id,
        "chunk_size": chunk_size,
    }


__all__ = ["MAX_BATCH", "MAX_LEN", "NormalizeError", "VALID_AAS", "normalize_args"]

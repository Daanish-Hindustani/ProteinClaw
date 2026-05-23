"""AlphaFold2-multimer input validation — host-importable."""

from __future__ import annotations

import re
from typing import Any

MAX_LEN = 1024
MIN_LEN = 5
_AMBIGUITY = set("XBZJUO")  # AAs ESMFold/AF2 don't reliably handle
_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")
_NON_AA_RE = re.compile(r"[^ACDEFGHIKLMNPQRSTVWY]")


class NormalizeError(ValueError):
    """Raised when input arguments are invalid."""


def _clean_seq(label: str, raw: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise NormalizeError(f"{label} must be a non-empty string")
    s = raw.strip().upper()
    if not s:
        raise NormalizeError(f"{label} cannot be whitespace-only")
    if len(s) < MIN_LEN or len(s) > MAX_LEN:
        raise NormalizeError(
            f"{label} length must be {MIN_LEN}..{MAX_LEN}, got {len(s)}"
        )
    bad = _NON_AA_RE.search(s)
    if bad:
        ch = bad.group()
        hint = (
            " (ambiguity code — AF2 doesn't handle these reliably)"
            if ch in _AMBIGUITY
            else ""
        )
        raise NormalizeError(
            f"{label} contains non-standard residue {ch!r}{hint}"
        )
    return s


def normalize_args(
    *,
    binder_sequence: str,
    target_sequence: str,
    relax_prediction: bool = False,
    msa_source: str = "colabfold",
    num_recycle: int = 3,
    num_models: int = 1,
    step: int = 0,
    session_id: str = "",
) -> dict[str, Any]:
    binder = _clean_seq("binder_sequence", binder_sequence)
    target = _clean_seq("target_sequence", target_sequence)
    if msa_source not in {"colabfold", "single_sequence"}:
        raise NormalizeError(
            f"msa_source must be 'colabfold' or 'single_sequence', got {msa_source!r}"
        )
    if not isinstance(num_recycle, int) or not 1 <= num_recycle <= 24:
        raise NormalizeError(f"num_recycle must be 1..24, got {num_recycle!r}")
    if not isinstance(num_models, int) or not 1 <= num_models <= 5:
        raise NormalizeError(f"num_models must be 1..5, got {num_models!r}")
    if not isinstance(step, int) or step < 0:
        raise NormalizeError(f"step must be >= 0, got {step!r}")
    return {
        "binder_sequence": binder,
        "target_sequence": target,
        "relax_prediction": bool(relax_prediction),
        "msa_source": msa_source,
        "num_recycle": num_recycle,
        "num_models": num_models,
        "step": int(step),
        "session_id": session_id,
    }


def average_chain_plddt(pdb_text: str, chain_id: str) -> tuple[float, int]:
    """Return ``(mean_plddt_over_CA, num_residues_seen)`` for ``chain_id``.

    AF2 writes per-residue pLDDT into the B-factor column (cols 61-66).
    Averaging over CA atoms gives the standard chain-pLDDT.
    """
    total = 0.0
    n = 0
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 66:
            continue
        if line[13:15] != "CA":  # atom name field, left-justified
            # ATOM lines for CA are " CA " in the atom-name 4-char field.
            # Be tolerant: also accept "CA  " etc.
            if " CA " not in line[12:16] + " ":
                continue
        if line[21:22] != chain_id:
            continue
        try:
            bfac = float(line[60:66].strip())
        except ValueError:
            continue
        total += bfac
        n += 1
    if n == 0:
        return 0.0, 0
    return total / n, n


__all__ = ["MAX_LEN", "MIN_LEN", "NormalizeError", "average_chain_plddt", "normalize_args"]

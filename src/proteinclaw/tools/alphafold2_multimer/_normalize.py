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
    ipsae_pae_cutoff: float = 10.0,
    ipsae_dist_cutoff: float = 10.0,
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
    for label, cut in (
        ("ipsae_pae_cutoff", ipsae_pae_cutoff),
        ("ipsae_dist_cutoff", ipsae_dist_cutoff),
    ):
        if isinstance(cut, bool) or not isinstance(cut, (int, float)):
            raise NormalizeError(f"{label} must be a number, got {cut!r}")
        if not 0 < cut <= 99:
            raise NormalizeError(f"{label} must be in (0, 99], got {cut!r}")
    return {
        "binder_sequence": binder,
        "target_sequence": target,
        "relax_prediction": bool(relax_prediction),
        "msa_source": msa_source,
        "num_recycle": num_recycle,
        "num_models": num_models,
        "step": int(step),
        "session_id": session_id,
        "ipsae_pae_cutoff": float(ipsae_pae_cutoff),
        "ipsae_dist_cutoff": float(ipsae_dist_cutoff),
    }


# ipsae.py (Dunbrack Lab, MIT) writes a whitespace-delimited summary table.
# We map our envelope keys to its column header names so a future column
# addition upstream doesn't shift our parsing.
_IPSAE_COLS = {
    "ipsae": "ipSAE",
    "ipsae_d0chn": "ipSAE_d0chn",
    "iptm": "ipTM_af",
    "pdockq": "pDockQ",
    "pdockq2": "pDockQ2",
    "lis": "LIS",
}
_IPSAE_EMPTY = {k: None for k in _IPSAE_COLS}


def parse_ipsae_txt(
    text: str, binder_chain: str = "A", target_chain: str = "B"
) -> dict[str, Any]:
    """Parse ipsae.py's summary ``.txt`` for one chain pair.

    Returns ``{ipsae, ipsae_d0chn, iptm, pdockq, pdockq2, lis}`` (floats),
    using the ``Type == "max"`` row for the binder/target pair (ipSAE is
    asymmetric; the ``max`` row carries the per-metric max over both
    directions, which is the script's headline value). Falls back to taking
    the max over the two ``asym`` rows if no ``max`` row is present. On any
    parse failure every value is ``None`` — callers treat this as "ipSAE
    unavailable", never as a hard error.
    """
    pair = {binder_chain, target_chain}
    try:
        header: list[str] | None = None
        idx: dict[str, int] = {}
        rows: list[list[str]] = []
        for line in text.splitlines():
            toks = line.split()
            if not toks:
                continue
            if header is None:
                if "Chn1" in toks and "ipSAE" in toks:
                    header = toks
                    idx = {name: i for i, name in enumerate(toks)}
                continue
            # Data row: must have the columns we need + a chain pair match.
            if len(toks) < len(header):
                continue
            if {toks[idx["Chn1"]], toks[idx["Chn2"]]} != pair:
                continue
            rows.append(toks)
        if header is None or not rows:
            return dict(_IPSAE_EMPTY)

        def _row_metrics(row: list[str]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key, col in _IPSAE_COLS.items():
                try:
                    out[key] = float(row[idx[col]])
                except (KeyError, IndexError, ValueError):
                    out[key] = None
            return out

        max_rows = [r for r in rows if "Type" in idx and r[idx["Type"]] == "max"]
        if max_rows:
            return _row_metrics(max_rows[0])
        # No explicit max row — take the per-metric max over directional rows.
        per_row = [_row_metrics(r) for r in rows]
        merged: dict[str, Any] = {}
        for key in _IPSAE_COLS:
            vals = [m[key] for m in per_row if m[key] is not None]
            merged[key] = max(vals) if vals else None
        return merged
    except Exception:  # noqa: BLE001 — supplementary metric, never crash the run
        return dict(_IPSAE_EMPTY)


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


__all__ = [
    "MAX_LEN",
    "MIN_LEN",
    "NormalizeError",
    "average_chain_plddt",
    "normalize_args",
    "parse_ipsae_txt",
]

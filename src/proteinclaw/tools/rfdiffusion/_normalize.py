"""Pure input validation for RFdiffusion — host-importable for unit tests.

Encapsulates the parsing of hotspot residue strings and binder length
specifications so the test suite can hammer the edge cases without spinning
up Docker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

WORKSPACE_ROOT = "/workspace"
_HOTSPOT_TOKEN_RE = re.compile(r"^([A-Za-z])(\d+)$")
_LENGTH_RE = re.compile(r"^(\d+)(?:-(\d+))?$")
_CHAIN_RE = re.compile(r"^[A-Za-z]$")


class NormalizeError(ValueError):
    """Raised when input arguments are invalid."""


def parse_hotspot_residues(spec: str, target_chain: str) -> list[str]:
    """Parse a comma-separated hotspot string into a validated token list.

    Each token must be ``<chain><residue_number>`` and the chain MUST equal
    ``target_chain`` — RFdiffusion's hotspot model expects all hotspots on
    the same chain as the target.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise NormalizeError("hotspot_residues must be a non-empty string")
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise NormalizeError("hotspot_residues had no usable tokens after splitting on ','")
    cleaned: list[str] = []
    for t in tokens:
        m = _HOTSPOT_TOKEN_RE.match(t)
        if not m:
            raise NormalizeError(
                f"hotspot {t!r} must match '<chain><residue_number>' (e.g. 'A30')"
            )
        chain, num = m.group(1).upper(), m.group(2)
        if chain != target_chain.upper():
            raise NormalizeError(
                f"hotspot {t!r} on chain {chain!r} does not match target_chain={target_chain!r}"
            )
        cleaned.append(f"{chain}{num}")
    return cleaned


def parse_binder_length(spec: str) -> tuple[int, int]:
    """Parse '70' or '60-90' into ``(min_len, max_len)``."""
    if not isinstance(spec, str):
        raise NormalizeError(f"binder_length must be a string, got {type(spec).__name__}")
    m = _LENGTH_RE.match(spec.strip())
    if not m:
        raise NormalizeError(
            f"binder_length {spec!r} must be 'N' or 'N-M' (positive integers)"
        )
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    if lo < 5 or hi > 500:
        raise NormalizeError(
            f"binder_length must be 5..500, got {lo}-{hi}"
        )
    if lo > hi:
        raise NormalizeError(f"binder_length lower bound {lo} > upper bound {hi}")
    return lo, hi


def parse_chain_ranges(pdb_text: str) -> dict[str, tuple[int, int]]:
    """Scan ATOM records and return ``{chain_id: (min_resi, max_resi)}``.

    Used to (a) confirm the requested target_chain exists and (b) build the
    contigmap.contigs string with the right residue range.
    """
    ranges: dict[str, tuple[int, int]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        chain = line[21:22]
        try:
            resi = int(line[22:26].strip())
        except ValueError:
            continue
        prev = ranges.get(chain)
        if prev is None:
            ranges[chain] = (resi, resi)
        else:
            ranges[chain] = (min(prev[0], resi), max(prev[1], resi))
    return ranges


def normalize_args(
    *,
    target_pdb: str,
    hotspot_residues: str,
    target_chain: str = "A",
    binder_length: str = "70",
    num_designs: int = 4,
    diffuser_T: int = 50,
    use_complex_weights: bool = True,
    step: int = 0,
    session_id: str = "",
    workspace_root: str = WORKSPACE_ROOT,
    skip_path_check: bool = False,
) -> dict[str, Any]:
    if not isinstance(num_designs, int) or not 1 <= num_designs <= 32:
        raise NormalizeError(f"num_designs must be 1..32, got {num_designs!r}")
    if not isinstance(diffuser_T, int) or not 10 <= diffuser_T <= 200:
        raise NormalizeError(f"diffuser_T must be 10..200, got {diffuser_T!r}")
    if not _CHAIN_RE.match(target_chain):
        raise NormalizeError(f"target_chain must be one letter, got {target_chain!r}")
    if not target_pdb:
        raise NormalizeError("target_pdb is required")

    target_chain = target_chain.upper()
    hotspots = parse_hotspot_residues(hotspot_residues, target_chain)
    bl_lo, bl_hi = parse_binder_length(binder_length)

    target = Path(target_pdb)
    if not target.is_absolute():
        target = Path(workspace_root) / target

    chain_ranges: dict[str, tuple[int, int]] = {}
    if not skip_path_check:
        ws_prefix = workspace_root.rstrip("/") + "/"
        if not str(target).startswith(ws_prefix) and str(target) != workspace_root:
            raise NormalizeError(
                f"target_pdb must live under {workspace_root}/, got {target}"
            )
        if not target.exists():
            raise NormalizeError(f"target PDB not found: {target}")
        if target.suffix.lower() != ".pdb":
            raise NormalizeError(f"target must be a .pdb file, got {target.name}")
        pdb_text = target.read_text(encoding="utf-8", errors="replace")
        chain_ranges = parse_chain_ranges(pdb_text)
        if target_chain not in chain_ranges:
            raise NormalizeError(
                f"target_chain {target_chain!r} not found in PDB (chains present: {sorted(chain_ranges)})"
            )
        # Validate every hotspot residue is within the target chain's range.
        rmin, rmax = chain_ranges[target_chain]
        for h in hotspots:
            resi = int(h[1:])
            if not rmin <= resi <= rmax:
                raise NormalizeError(
                    f"hotspot {h} out of chain {target_chain} residue range {rmin}-{rmax}"
                )

    return {
        "target_pdb": str(target),
        "target_chain": target_chain,
        "hotspot_residues": hotspots,
        "binder_length": (bl_lo, bl_hi),
        "num_designs": num_designs,
        "diffuser_T": diffuser_T,
        "use_complex_weights": use_complex_weights,
        "step": int(step),
        "session_id": session_id,
        "chain_ranges": chain_ranges,
    }


__all__ = [
    "NormalizeError",
    "normalize_args",
    "parse_binder_length",
    "parse_chain_ranges",
    "parse_hotspot_residues",
]

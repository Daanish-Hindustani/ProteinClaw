"""Pure input validation for RFantibody — host-importable for unit tests.

Parses hotspot residue strings, CDR loop length specifications, and
validates all scalar parameters. No GPU or container-only imports.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

WORKSPACE_ROOT = "/workspace"

_HOTSPOT_TOKEN_RE = re.compile(r"^([A-Za-z])(\d+)$")
_LOOP_TOKEN_RE = re.compile(r"^(H[123]|L[123]):((\d+)(?:-(\d+))?)$")
_CHAIN_RE = re.compile(r"^[A-Za-z]$")

# Valid CDR loops per framework type
_VHH_LOOPS = frozenset({"H1", "H2", "H3"})
_SCFV_LOOPS = frozenset({"H1", "H2", "H3", "L1", "L2", "L3"})


class NormalizeError(ValueError):
    """Raised when input arguments are invalid."""


# ---------------------------------------------------------------------------
# Hotspot parsing
# ---------------------------------------------------------------------------

def parse_hotspot_residues(spec: str, target_chain: str) -> list[str]:
    """Parse comma-separated ``<chain><resi>`` tokens.

    Chain letter must match *target_chain* (case-insensitive).
    Returns a list of upper-cased tokens, e.g. ``["A210", "A215"]``.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise NormalizeError("hotspot_residues must be a non-empty string")
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise NormalizeError("hotspot_residues contained no usable tokens")
    cleaned: list[str] = []
    for t in tokens:
        m = _HOTSPOT_TOKEN_RE.match(t)
        if not m:
            raise NormalizeError(
                f"hotspot {t!r} must match '<chain><residue_number>' (e.g. 'A210')"
            )
        chain, num = m.group(1).upper(), m.group(2)
        if chain != target_chain.upper():
            raise NormalizeError(
                f"hotspot {t!r} is on chain {chain!r} but target_chain={target_chain!r}"
            )
        cleaned.append(f"{chain}{num}")
    return cleaned


def build_hotspot_arg(hotspots: list[str]) -> str:
    """Return the ``-h`` argument string, e.g. ``"A210,A215,A220"``."""
    return ",".join(hotspots)


# ---------------------------------------------------------------------------
# Loop length parsing
# ---------------------------------------------------------------------------

def parse_loop_lengths(
    spec: Optional[str],
    framework_type: str,
) -> dict[str, tuple[int, int]]:
    """Parse CDR loop length spec: ``"H1:7,H2:6,H3:15-22"``.

    Returns a dict mapping loop name → (lo, hi) integer pair. An empty
    spec or None returns an empty dict (all loops use RFantibody defaults).
    """
    if not spec:
        return {}
    valid = _VHH_LOOPS if framework_type == "vhh" else _SCFV_LOOPS
    result: dict[str, tuple[int, int]] = {}
    for raw in [t.strip() for t in spec.split(",") if t.strip()]:
        m = _LOOP_TOKEN_RE.match(raw)
        if not m:
            raise NormalizeError(
                f"loop_lengths token {raw!r} must be '<loop>:<n>' or '<loop>:<n>-<m>'"
                f" e.g. 'H3:15-22'"
            )
        loop, lo_str, hi_str = m.group(1), m.group(3), m.group(4)
        if loop not in valid:
            raise NormalizeError(
                f"loop {loop!r} is not valid for framework_type={framework_type!r}; "
                f"valid loops: {sorted(valid)}"
            )
        lo = int(lo_str)
        hi = int(hi_str) if hi_str else lo
        if lo < 1 or hi > 30:
            raise NormalizeError(
                f"loop {loop!r} length {lo}-{hi} out of range 1..30"
            )
        if lo > hi:
            raise NormalizeError(
                f"loop {loop!r}: lower bound {lo} > upper bound {hi}"
            )
        result[loop] = (lo, hi)
    return result


def build_loop_lengths_arg(loop_lengths: dict[str, tuple[int, int]]) -> Optional[str]:
    """Build the ``-l`` argument string, e.g. ``"H1:7,H2:6,H3:15-22"``."""
    if not loop_lengths:
        return None
    parts: list[str] = []
    for loop, (lo, hi) in sorted(loop_lengths.items()):
        parts.append(f"{loop}:{lo}" if lo == hi else f"{loop}:{lo}-{hi}")
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Main normalizer
# ---------------------------------------------------------------------------

def normalize_args(
    *,
    target_pdb: str,
    hotspot_residues: str,
    target_chain: str = "A",
    framework_type: str = "vhh",
    framework_pdb: Optional[str] = None,
    loop_lengths: Optional[str] = None,
    num_designs: int = 10,
    seqs_per_struct: int = 4,
    temperature: float = 0.2,
    num_recycles: int = 10,
    pae_threshold: float = 10.0,
    rmsd_threshold: float = 2.0,
    step: int = 0,
    session_id: str = "",
    workspace_root: str = WORKSPACE_ROOT,
    skip_path_check: bool = False,
) -> dict[str, Any]:
    """Validate all inputs and return a normalised args dict."""
    # Chain letter
    if not _CHAIN_RE.match(target_chain):
        raise NormalizeError(
            f"target_chain must be a single letter, got {target_chain!r}"
        )
    target_chain = target_chain.upper()

    # framework_type
    if framework_type not in ("vhh", "scfv"):
        raise NormalizeError(
            f"framework_type must be 'vhh' or 'scfv', got {framework_type!r}"
        )

    # Integer scalars
    if not isinstance(num_designs, int) or not 1 <= num_designs <= 100:
        raise NormalizeError(f"num_designs must be 1..100, got {num_designs!r}")
    if not isinstance(seqs_per_struct, int) or not 1 <= seqs_per_struct <= 10:
        raise NormalizeError(f"seqs_per_struct must be 1..10, got {seqs_per_struct!r}")
    if not isinstance(num_recycles, int) or not 1 <= num_recycles <= 20:
        raise NormalizeError(f"num_recycles must be 1..20, got {num_recycles!r}")

    # Float scalars
    try:
        temp_f = float(temperature)
    except (TypeError, ValueError):
        raise NormalizeError(f"temperature must be numeric, got {temperature!r}")
    if not 0.01 <= temp_f <= 1.0:
        raise NormalizeError(f"temperature must be 0.01..1.0, got {temperature!r}")

    try:
        pae_f = float(pae_threshold)
        rmsd_f = float(rmsd_threshold)
    except (TypeError, ValueError):
        raise NormalizeError("pae_threshold and rmsd_threshold must be numeric")
    if not 1.0 <= pae_f <= 20.0:
        raise NormalizeError(f"pae_threshold must be 1.0..20.0, got {pae_threshold!r}")
    if not 0.5 <= rmsd_f <= 5.0:
        raise NormalizeError(f"rmsd_threshold must be 0.5..5.0, got {rmsd_threshold!r}")

    # Hotspots
    hotspots = parse_hotspot_residues(hotspot_residues, target_chain)

    # Loop lengths
    parsed_loops = parse_loop_lengths(loop_lengths, framework_type)

    # Paths
    target = Path(target_pdb)
    if not target.is_absolute():
        target = Path(workspace_root) / target

    fw_path_str: Optional[str] = None
    if not skip_path_check:
        ws_prefix = workspace_root.rstrip("/") + "/"
        if not str(target).startswith(ws_prefix):
            raise NormalizeError(
                f"target_pdb must live under {workspace_root}/, got {target}"
            )
        if not target.exists():
            raise NormalizeError(f"target PDB not found: {target}")
        if target.suffix.lower() not in {".pdb", ".cif"}:
            raise NormalizeError(
                f"target_pdb must be .pdb or .cif, got {target.name!r}"
            )
        if framework_pdb is not None:
            fw = Path(framework_pdb)
            if not fw.is_absolute():
                fw = Path(workspace_root) / fw
            if not fw.exists():
                raise NormalizeError(f"framework_pdb not found: {fw}")
            fw_path_str = str(fw)
    else:
        if framework_pdb is not None:
            fw_path_str = framework_pdb

    return {
        "target_pdb": str(target),
        "target_chain": target_chain,
        "hotspot_residues": hotspots,
        "framework_type": framework_type,
        "framework_pdb": fw_path_str,
        "loop_lengths": parsed_loops,
        "num_designs": num_designs,
        "seqs_per_struct": seqs_per_struct,
        "temperature": temp_f,
        "num_recycles": num_recycles,
        "pae_threshold": pae_f,
        "rmsd_threshold": rmsd_f,
        "step": int(step),
        "session_id": session_id,
    }


__all__ = [
    "NormalizeError",
    "build_hotspot_arg",
    "build_loop_lengths_arg",
    "normalize_args",
    "parse_hotspot_residues",
    "parse_loop_lengths",
]

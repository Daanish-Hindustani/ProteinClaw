"""Pure input validation for RFD3 — host-importable for unit tests.

Parses hotspot strings, binder length specs, and the target PDB chain ranges.
Also picks default side-chain atoms per hotspot residue (CA + CB for non-Gly,
CA only for Gly) — these feed into the RFD3 `select_hotspots` JSON field.
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
    """Parse comma-separated ``<chain><resi>`` tokens; chain must match target."""
    if not isinstance(spec, str) or not spec.strip():
        raise NormalizeError("hotspot_residues must be a non-empty string")
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise NormalizeError("hotspot_residues had no usable tokens")
    cleaned: list[str] = []
    for t in tokens:
        m = _HOTSPOT_TOKEN_RE.match(t)
        if not m:
            raise NormalizeError(
                f"hotspot {t!r} must match '<chain><residue_number>' (e.g. 'A56')"
            )
        chain, num = m.group(1).upper(), m.group(2)
        if chain != target_chain.upper():
            raise NormalizeError(
                f"hotspot {t!r} on chain {chain!r} != target_chain={target_chain!r}"
            )
        cleaned.append(f"{chain}{num}")
    return cleaned


def parse_binder_length(spec: str) -> tuple[int, int]:
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
        raise NormalizeError(f"binder_length must be 5..500, got {lo}-{hi}")
    if lo > hi:
        raise NormalizeError(f"binder_length lower bound {lo} > upper bound {hi}")
    return lo, hi


def parse_chain_ranges_and_resmap(pdb_text: str) -> tuple[dict[str, tuple[int, int]], dict[tuple[str, int], str]]:
    """Scan ATOM/HETATM records.

    Returns ``(chain_ranges, residue_types)`` where:
      * ``chain_ranges[chain] = (min_resi, max_resi)``
      * ``residue_types[(chain, resi)] = "ALA"``-style 3-letter code
    """
    ranges: dict[str, tuple[int, int]] = {}
    types: dict[tuple[str, int], str] = {}
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
        resn = line[17:20].strip().upper()
        prev = ranges.get(chain)
        if prev is None:
            ranges[chain] = (resi, resi)
        else:
            ranges[chain] = (min(prev[0], resi), max(prev[1], resi))
        types[(chain, resi)] = resn
    return ranges, types


def default_atoms_for_residue(resn: str) -> str:
    """CA+CB pair — covers 19/20 standard amino acids. CA-only for Gly."""
    return "CA" if resn == "GLY" else "CA,CB"


def build_hotspot_atom_map(
    hotspots: list[str],
    residue_types: dict[tuple[str, int], str],
    overrides: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Produce the `select_hotspots` mapping {token: "ATOM1,ATOM2"}."""
    out: dict[str, str] = {}
    for token in hotspots:
        if overrides and token in overrides:
            out[token] = overrides[token]
            continue
        chain = token[0]
        resi = int(token[1:])
        resn = residue_types.get((chain, resi), "")
        out[token] = default_atoms_for_residue(resn) if resn else "CA"
    return out


def normalize_args(
    *,
    target_pdb: str,
    hotspot_residues: str,
    target_chain: str = "A",
    hotspot_atoms: Optional[dict[str, str]] = None,
    binder_length: str = "70",
    num_designs: int = 4,
    num_timesteps: int = 200,
    step_scale: float = 3.0,
    gamma_0: float = 0.2,
    is_non_loopy: bool = True,
    step: int = 0,
    session_id: str = "",
    workspace_root: str = WORKSPACE_ROOT,
    skip_path_check: bool = False,
) -> dict[str, Any]:
    if not isinstance(num_designs, int) or not 1 <= num_designs <= 32:
        raise NormalizeError(f"num_designs must be 1..32, got {num_designs!r}")
    if not isinstance(num_timesteps, int) or not 10 <= num_timesteps <= 400:
        raise NormalizeError(f"num_timesteps must be 10..400, got {num_timesteps!r}")
    try:
        step_scale_f = float(step_scale)
    except (TypeError, ValueError):
        raise NormalizeError(f"step_scale must be numeric, got {step_scale!r}")
    if not 0.5 <= step_scale_f <= 5.0:
        raise NormalizeError(f"step_scale must be 0.5..5.0, got {step_scale!r}")
    try:
        gamma_0_f = float(gamma_0)
    except (TypeError, ValueError):
        raise NormalizeError(f"gamma_0 must be numeric, got {gamma_0!r}")
    if not 0.0 <= gamma_0_f <= 1.0:
        raise NormalizeError(f"gamma_0 must be 0.0..1.0, got {gamma_0!r}")
    if not _CHAIN_RE.match(target_chain):
        raise NormalizeError(f"target_chain must be one letter, got {target_chain!r}")
    if not target_pdb:
        raise NormalizeError("target_pdb is required")
    if hotspot_atoms is not None and not isinstance(hotspot_atoms, dict):
        raise NormalizeError("hotspot_atoms must be a dict if provided")

    target_chain = target_chain.upper()
    hotspots = parse_hotspot_residues(hotspot_residues, target_chain)
    bl_lo, bl_hi = parse_binder_length(binder_length)

    target = Path(target_pdb)
    if not target.is_absolute():
        target = Path(workspace_root) / target

    chain_ranges: dict[str, tuple[int, int]] = {}
    residue_types: dict[tuple[str, int], str] = {}
    if not skip_path_check:
        ws_prefix = workspace_root.rstrip("/") + "/"
        if not str(target).startswith(ws_prefix) and str(target) != workspace_root:
            raise NormalizeError(
                f"target_pdb must live under {workspace_root}/, got {target}"
            )
        if not target.exists():
            raise NormalizeError(f"target PDB not found: {target}")
        if target.suffix.lower() not in {".pdb", ".cif"}:
            raise NormalizeError(f"target must be .pdb or .cif, got {target.name}")
        pdb_text = target.read_text(encoding="utf-8", errors="replace")
        chain_ranges, residue_types = parse_chain_ranges_and_resmap(pdb_text)
        if target_chain not in chain_ranges:
            raise NormalizeError(
                f"target_chain {target_chain!r} not in PDB (present: {sorted(chain_ranges)})"
            )
        rmin, rmax = chain_ranges[target_chain]
        for h in hotspots:
            resi = int(h[1:])
            if not rmin <= resi <= rmax:
                raise NormalizeError(
                    f"hotspot {h} out of chain {target_chain} range {rmin}-{rmax}"
                )

    select_hotspots = build_hotspot_atom_map(hotspots, residue_types, hotspot_atoms)

    return {
        "target_pdb": str(target),
        "target_chain": target_chain,
        "hotspot_residues": hotspots,
        "select_hotspots": select_hotspots,
        "binder_length": (bl_lo, bl_hi),
        "num_designs": num_designs,
        "num_timesteps": num_timesteps,
        "step_scale": step_scale_f,
        "gamma_0": gamma_0_f,
        "is_non_loopy": bool(is_non_loopy),
        "step": int(step),
        "session_id": session_id,
        "chain_ranges": chain_ranges,
    }


def chain_ca_counts(pdb_text: str) -> dict[str, int]:
    """Count CA atoms per chain in a PDB string (host-side mirror of the
    container helper, kept here so partial-diffusion normalization can size
    the binder/target chains without importing container-only code)."""
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


def normalize_partial_args(
    *,
    start_pdb: str,
    partial_t: float,
    binder_chain: str = "A",
    target_chain: str = "B",
    num_designs: int = 4,
    num_timesteps: int = 200,
    step_scale: float = 3.0,
    gamma_0: float = 0.2,
    is_non_loopy: bool = True,
    step: int = 0,
    session_id: str = "",
    workspace_root: str = WORKSPACE_ROOT,
    skip_path_check: bool = False,
    **_ignored: Any,
) -> dict[str, Any]:
    """Validate args for partial-diffusion mode (refine an existing complex).

    Unlike de-novo mode there is no contig/length/hotspots — RFD3 re-noises
    the whole ``start_pdb`` complex by ``partial_t`` Angstroms. We still parse
    the input so the output-classification path (binder vs target chain) has
    the same ``binder_length``/``target_chain``/``chain_ranges`` keys it needs.
    """
    try:
        partial_t_f = float(partial_t)
    except (TypeError, ValueError):
        raise NormalizeError(f"partial_t must be numeric, got {partial_t!r}")
    if not 0.0 < partial_t_f <= 15.0:
        raise NormalizeError(f"partial_t must be in (0, 15] Angstroms, got {partial_t_f}")
    if not isinstance(num_designs, int) or not 1 <= num_designs <= 32:
        raise NormalizeError(f"num_designs must be 1..32, got {num_designs!r}")
    if not isinstance(num_timesteps, int) or not 10 <= num_timesteps <= 400:
        raise NormalizeError(f"num_timesteps must be 10..400, got {num_timesteps!r}")
    try:
        step_scale_f = float(step_scale)
    except (TypeError, ValueError):
        raise NormalizeError(f"step_scale must be numeric, got {step_scale!r}")
    if not 0.5 <= step_scale_f <= 5.0:
        raise NormalizeError(f"step_scale must be 0.5..5.0, got {step_scale!r}")
    try:
        gamma_0_f = float(gamma_0)
    except (TypeError, ValueError):
        raise NormalizeError(f"gamma_0 must be numeric, got {gamma_0!r}")
    if not 0.0 <= gamma_0_f <= 1.0:
        raise NormalizeError(f"gamma_0 must be 0.0..1.0, got {gamma_0!r}")
    if not start_pdb:
        raise NormalizeError("start_pdb is required for partial diffusion")
    if not _CHAIN_RE.match(binder_chain):
        raise NormalizeError(f"binder_chain must be one letter, got {binder_chain!r}")
    if not _CHAIN_RE.match(target_chain):
        raise NormalizeError(f"target_chain must be one letter, got {target_chain!r}")
    binder_chain = binder_chain.upper()
    target_chain = target_chain.upper()
    if binder_chain == target_chain:
        raise NormalizeError(
            f"binder_chain and target_chain must differ (both {binder_chain!r})"
        )

    start = Path(start_pdb)
    if not start.is_absolute():
        start = Path(workspace_root) / start

    chain_ranges: dict[str, tuple[int, int]] = {}
    binder_len = 0
    if not skip_path_check:
        ws_prefix = workspace_root.rstrip("/") + "/"
        if not str(start).startswith(ws_prefix) and str(start) != workspace_root:
            raise NormalizeError(
                f"start_pdb must live under {workspace_root}/, got {start}"
            )
        if not start.exists():
            raise NormalizeError(f"start_pdb not found: {start}")
        if start.suffix.lower() not in {".pdb", ".cif"}:
            raise NormalizeError(f"start_pdb must be .pdb or .cif, got {start.name}")
        pdb_text = start.read_text(encoding="utf-8", errors="replace")
        chain_ranges, _ = parse_chain_ranges_and_resmap(pdb_text)
        counts = chain_ca_counts(pdb_text)
        for needed in (binder_chain, target_chain):
            if needed not in counts:
                raise NormalizeError(
                    f"chain {needed!r} not in start_pdb (present: {sorted(counts)})"
                )
        binder_len = counts[binder_chain]

    return {
        "partial_t": partial_t_f,
        "start_pdb": str(start),
        "target_pdb": str(start),  # compat: some callers read this key
        "binder_chain": binder_chain,
        "target_chain": target_chain,
        "hotspot_residues": [],
        "select_hotspots": {},
        # (lo, hi) tightly around the input binder so the output classifier
        # can still tell the re-diffused binder from the target chain.
        "binder_length": (binder_len, binder_len),
        "num_designs": num_designs,
        "num_timesteps": num_timesteps,
        "step_scale": step_scale_f,
        "gamma_0": gamma_0_f,
        "is_non_loopy": bool(is_non_loopy),
        "step": int(step),
        "session_id": session_id,
        "chain_ranges": chain_ranges,
    }


def build_input_spec(args: dict[str, Any], *, spec_name: str = "binder") -> dict[str, Any]:
    """Build the JSON the RFD3 ``inputs=`` flag expects (one entry per spec)."""
    if args.get("partial_t") is not None:
        # Partial diffusion: hand RFD3 the whole prior complex + a noise scale.
        # No contig/length — RFD3 re-noises the input "without constraints".
        return {
            spec_name: {
                "dialect": 2,
                "input": args["start_pdb"],
                "partial_t": float(args["partial_t"]),
                "is_non_loopy": args["is_non_loopy"],
            }
        }
    chain_range = args["chain_ranges"].get(args["target_chain"])
    if chain_range is None:
        # Caller used skip_path_check — fall back to a generic range; this
        # is fine for unit tests but not for live inference.
        chain_range = (1, 200)
    bl_lo, bl_hi = args["binder_length"]
    contig = f"{bl_lo}-{bl_hi},/0,{args['target_chain']}{chain_range[0]}-{chain_range[1]}"
    return {
        spec_name: {
            "dialect": 2,
            "infer_ori_strategy": "hotspots",
            "input": args["target_pdb"],
            "contig": contig,
            "select_hotspots": dict(args["select_hotspots"]),
            "is_non_loopy": args["is_non_loopy"],
        }
    }


__all__ = [
    "NormalizeError",
    "build_hotspot_atom_map",
    "build_input_spec",
    "chain_ca_counts",
    "default_atoms_for_residue",
    "normalize_args",
    "normalize_partial_args",
    "parse_binder_length",
    "parse_chain_ranges_and_resmap",
    "parse_hotspot_residues",
]

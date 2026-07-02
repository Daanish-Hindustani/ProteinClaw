"""``data.pdb_fetch`` — download a PDB structure from RCSB.

Caches the full ``.pdb`` file at ``~/.cache/proteinclaw/pdb/<id>.pdb`` so
repeat calls don't re-hit RCSB. Optional ``chain`` and ``crop`` produce a
filtered sub-PDB written into the session workspace; the full file is always
kept too so the agent can re-crop later if needed.

PRD §6.4: RCSB is the primary structure source. No AlphaFold DB fallback in
v1 — 404 is a hard failure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import requests

from proteinclaw.tools import registry
from proteinclaw.tools._http import get_text, make_session
from proteinclaw.tools._paths import tool_cache_dir, tool_output_dir

RCSB_FILE_URL = "https://files.rcsb.org/download/{id}.pdb"

# PDB IDs are 4 chars: digit + 3 alphanum. Case-insensitive on input; RCSB
# normalises to uppercase in the file path.
_PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
_CROP_RE = re.compile(r"^(\d+)-(\d+)$")

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pdb_id": {
            "type": "string",
            "pattern": "^[0-9][A-Za-z0-9]{3}$",
            "description": "4-character PDB identifier (e.g. '5JDS').",
        },
        "chain": {
            "type": "string",
            "pattern": "^[A-Za-z0-9]$",
            "description": "Optional single-letter chain ID to extract.",
        },
        "crop": {
            "type": "string",
            "pattern": "^\\d+-\\d+$",
            "description": "Optional residue range 'M-N' (inclusive) to crop within the selected chain.",
        },
        "session_id": {
            "type": "string",
            "description": "Per-run session id; cropped PDBs land under the session workspace.",
        },
        "step": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Step index for the output subdirectory (per-tool counter).",
        },
    },
    "required": ["pdb_id"],
}

_ANALYZE_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "pdb_path": {
            "type": "string",
            "minLength": 1,
            "description": "Path to a local PDB file returned by ProteinClaw tools or present in the run workspace.",
        },
        "chain": {
            "type": "string",
            "pattern": "^[A-Za-z0-9]$",
            "description": "Optional chain to highlight in the analysis.",
        },
        "hotspot_residues": {
            "type": "string",
            "description": "Optional comma-separated target hotspots such as 'A44,A68,A70' or '44,68,70'.",
        },
        "binder_chain": {
            "type": "string",
            "pattern": "^[A-Za-z0-9]$",
            "description": "Optional binder chain for two-chain interface analysis.",
        },
        "target_chain": {
            "type": "string",
            "pattern": "^[A-Za-z0-9]$",
            "description": "Optional target chain for two-chain interface analysis.",
        },
        "crop_start": {
            "type": "integer",
            "description": "First original target residue number when AF2/RFD3 renumbered the target chain from 1.",
        },
        "cdr_ranges": {
            "type": "string",
            "description": "Nanobody only: JSON CDR ranges to pass through to interface metrics.",
        },
    },
    "required": ["pdb_path"],
}

_AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def _parse_crop(crop: str) -> tuple[int, int]:
    m = _CROP_RE.match(crop)
    if not m:
        raise ValueError(f"crop must be 'M-N' integer range, got {crop!r}")
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        raise ValueError(f"crop lower bound {lo} > upper bound {hi}")
    return lo, hi


def _is_atom_line(line: str) -> bool:
    return line.startswith(("ATOM  ", "HETATM"))


def _line_chain(line: str) -> str:
    # PDB column 22 (1-indexed) = chain identifier.
    return line[21:22] if len(line) >= 22 else ""


def _line_resi(line: str) -> Optional[int]:
    # Cols 23-26 = residue sequence number.
    raw = line[22:26].strip() if len(line) >= 26 else ""
    try:
        return int(raw)
    except ValueError:
        return None


def _line_atom_name(line: str) -> str:
    return line[12:16].strip() if len(line) >= 16 else ""


def _line_resname(line: str) -> str:
    return line[17:20].strip() if len(line) >= 20 else ""


def _line_xyz(line: str) -> tuple[float, float, float] | None:
    try:
        return (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    except ValueError:
        return None


def _line_bfactor(line: str) -> float | None:
    try:
        return float(line[60:66])
    except ValueError:
        return None


def _parse_hotspots(raw: str | None, default_chain: str | None = None) -> list[tuple[str | None, int]]:
    hotspots: list[tuple[str | None, int]] = []
    for token in (raw or "").split(","):
        t = token.strip()
        if not t:
            continue
        m = re.match(r"^([A-Za-z0-9])?(-?\d+)$", t)
        if not m:
            continue
        hotspots.append((m.group(1) or default_chain, int(m.group(2))))
    return hotspots


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _chain_summary_from_atoms(lines: list[str]) -> list[dict[str, Any]]:
    per_chain: dict[str, dict[str, Any]] = {}
    for line in lines:
        ch = _line_chain(line) or "_"
        resi = _line_resi(line)
        if resi is None:
            continue
        atom = _line_atom_name(line)
        resname = _line_resname(line)
        xyz = _line_xyz(line)
        b = _line_bfactor(line)
        rec = per_chain.setdefault(
            ch,
            {
                "chain": ch,
                "num_atoms": 0,
                "residues": {},
                "bfactors": [],
                "ca_bfactors": [],
                "coords": [],
            },
        )
        rec["num_atoms"] += 1
        rec["residues"].setdefault(resi, resname)
        if b is not None:
            rec["bfactors"].append(b)
            if atom == "CA":
                rec["ca_bfactors"].append(b)
        if xyz is not None:
            rec["coords"].append(xyz)

    out: list[dict[str, Any]] = []
    for ch in sorted(per_chain):
        rec = per_chain[ch]
        residues = sorted(rec["residues"])
        gaps = [(a + 1, b - 1) for a, b in zip(residues, residues[1:]) if b > a + 1]
        coords = rec["coords"]
        sequence = "".join(_AA3_TO_1.get(rec["residues"][r], "X") for r in residues)
        item: dict[str, Any] = {
            "chain": ch,
            "num_atoms": rec["num_atoms"],
            "num_residues": len(residues),
            "first_residue": residues[0] if residues else None,
            "last_residue": residues[-1] if residues else None,
            "gaps": [{"start": lo, "end": hi} for lo, hi in gaps],
            "sequence": sequence,
            "sequence_preview": sequence[:120],
            "mean_bfactor": _mean(rec["bfactors"]),
            "mean_ca_bfactor": _mean(rec["ca_bfactors"]),
        }
        if coords:
            xs, ys, zs = zip(*coords)
            item["bbox"] = {
                "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
                "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
            }
        out.append(item)
    return out


def _hotspot_detail(lines: list[str], raw_hotspots: str | None, default_chain: str | None) -> list[dict[str, Any]]:
    parsed = _parse_hotspots(raw_hotspots, default_chain=default_chain)
    if not parsed:
        return []
    atoms: dict[tuple[str, int], list[str]] = {}
    for line in lines:
        resi = _line_resi(line)
        if resi is None:
            continue
        atoms.setdefault((_line_chain(line), resi), []).append(_line_atom_name(line))
    out: list[dict[str, Any]] = []
    for ch, resi in parsed:
        matches = []
        if ch is None:
            matches = [(key, names) for key, names in atoms.items() if key[1] == resi]
        else:
            names = atoms.get((ch, resi))
            if names is not None:
                matches = [((ch, resi), names)]
        out.append({
            "hotspot": f"{ch or ''}{resi}",
            "present": bool(matches),
            "matches": [
                {"chain": key[0], "residue": key[1], "num_atoms": len(names), "atoms": sorted(set(names))}
                for key, names in matches
            ],
        })
    return out


def _all_chain_summaries(text: str) -> list[dict[str, Any]]:
    """One-line summary per chain present in the PDB.

    Useful when the agent calls pdb_fetch without a chain filter to
    inspect what's available before deciding which to crop.
    """
    seen: dict[str, list[int]] = {}
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        ch = line[21:22]
        try:
            resi = int(line[22:26].strip())
        except ValueError:
            continue
        seen.setdefault(ch, []).append(resi)
    out: list[dict[str, Any]] = []
    for ch in sorted(seen):
        residues = sorted(set(seen[ch]))
        n_gaps = sum(1 for a, b in zip(residues, residues[1:]) if b > a + 1)
        out.append({
            "chain": ch,
            "first": residues[0],
            "last": residues[-1],
            "count": len(residues),
            "num_gaps": n_gaps,
            "summary": f"chain {ch}: {len(residues)} res {residues[0]}-{residues[-1]}"
                       + (f" ({n_gaps} gaps)" if n_gaps else " (contiguous)"),
        })
    return out


def _residues_present_in_chain(
    text: str, chain: str
) -> tuple[list[int], list[tuple[int, int]]]:
    """Return ``(sorted_residues, gaps)`` for ATOM records on ``chain``.

    ``gaps`` is a list of ``(lo, hi)`` inclusive ranges where residues are
    missing within the chain's overall range. Real-world crystals often
    have unmodeled loops; downstream tools (RFD3) reject contigs that
    span gaps, so the agent needs to know about them up front.
    """
    seen: set[int] = set()
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        if line[21:22] != chain:
            continue
        try:
            resi = int(line[22:26].strip())
        except ValueError:
            continue
        seen.add(resi)
    if not seen:
        return [], []
    residues = sorted(seen)
    gaps: list[tuple[int, int]] = []
    lo = residues[0]
    for prev, nxt in zip(residues, residues[1:]):
        if nxt > prev + 1:
            gaps.append((prev + 1, nxt - 1))
    _ = lo  # silence "unused"
    return residues, gaps


def _filter_pdb(
    text: str,
    *,
    chain: Optional[str],
    crop: Optional[tuple[int, int]],
) -> tuple[str, int, int]:
    """Return ``(filtered_text, num_atoms_kept, num_residues_kept)``.

    Non-coordinate records (HEADER, TITLE, REMARK, CRYST1, etc.) are
    preserved verbatim ahead of the kept ATOM/HETATM block. TER records are
    re-emitted only when at least one ATOM in the chain was kept.
    """
    kept_atoms = 0
    kept_residues: set[int] = set()
    out: list[str] = []
    for line in text.splitlines():
        if _is_atom_line(line):
            ch = _line_chain(line)
            if chain is not None and ch != chain:
                continue
            resi = _line_resi(line)
            if crop is not None:
                if resi is None or resi < crop[0] or resi > crop[1]:
                    continue
            out.append(line)
            kept_atoms += 1
            if resi is not None:
                kept_residues.add(resi)
        elif line.startswith("TER"):
            # Only keep TER records for chains we're including. Without this
            # we'd append the TER for a discarded chain just because a kept
            # chain was emitted earlier.
            if chain is None or _line_chain(line) == chain:
                out.append(line)
        elif line.startswith("END"):
            out.append(line)
        elif line.startswith("CONECT"):
            # CONECT records reference atom serial numbers. After
            # chain/crop filtering they often dangle — and downstream tools
            # (biotite/biopython, RFD3, AF2) reject the file with an
            # IndexError. Drop them; design tools infer connectivity from
            # atom types + coordinates anyway.
            continue
        else:
            # Header records: include unconditionally so PyMOL/Biopython are happy.
            out.append(line)
    return "\n".join(out) + "\n", kept_atoms, len(kept_residues)


def _download(pdb_id: str, session: requests.Session) -> tuple[int, str]:
    return get_text(RCSB_FILE_URL.format(id=pdb_id), session=session)


def _ensure_cached(
    pdb_id: str, session: requests.Session
) -> tuple[Optional[Path], Optional[dict[str, Any]]]:
    cache_dir = tool_cache_dir("pdb")
    cached = cache_dir / f"{pdb_id}.pdb"
    if cached.exists() and cached.stat().st_size > 0:
        return cached, None
    status, text = _download(pdb_id, session)
    if status == 404:
        return None, {
            "summary": f"Error: RCSB has no entry {pdb_id!r}",
            "error": "not_found",
            "metrics": {"http_status": 404},
        }
    if status >= 400:
        return None, {
            "summary": f"Error: RCSB returned HTTP {status} for {pdb_id!r}",
            "error": "upstream_error",
            "metrics": {"http_status": status},
        }
    if not text.lstrip().startswith(("HEADER", "ATOM", "HETATM", "REMARK", "TITLE", "MODEL", "DBREF")):
        return None, {
            "summary": f"Error: RCSB returned non-PDB content for {pdb_id!r}",
            "error": "bad_payload",
            "metrics": {"http_status": status, "bytes": len(text)},
        }
    cached.write_text(text, encoding="utf-8")
    return cached, None


@registry.register(
    name="data.pdb_fetch",
    display_name="PDB fetch (+ optional crop)",
    description=(
        "Download a structure from RCSB by PDB ID and cache it. Optionally extract "
        "a single chain and/or crop to a residue range, writing the filtered "
        "sub-PDB into the session workspace."
    ),
    category="data",
    parameters=_PARAMETERS,
    usage_guide=(
        "Pass `chain` to isolate a binding partner. Pass `crop='M-N'` to focus "
        "on a single domain (e.g. PD-L1 IgV: chain='A', crop='18-134')."
    ),
)
def pdb_fetch(
    *,
    pdb_id: str,
    chain: Optional[str] = None,
    crop: Optional[str] = None,
    session_id: Optional[str] = None,
    step: int = 0,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    pid = pdb_id.strip().upper()
    if not _PDB_ID_RE.match(pid):
        return {
            "summary": f"Error: {pdb_id!r} is not a 4-char PDB ID",
            "error": "invalid_query",
            "metrics": {},
        }
    crop_range: Optional[tuple[int, int]] = None
    if crop:
        try:
            crop_range = _parse_crop(crop)
        except ValueError as exc:
            return {
                "summary": f"Error: {exc}",
                "error": "invalid_query",
                "metrics": {},
            }

    sess = session or make_session()
    full_path, err = _ensure_cached(pid, sess)
    if err is not None:
        return err
    assert full_path is not None

    result: dict[str, Any] = {
        "pdb_id": pid,
        "pdb_path": str(full_path),
        "metrics": {"cache_path": str(full_path)},
    }

    text = full_path.read_text(encoding="utf-8")

    if chain is None and crop_range is None:
        # No chain filter — surface chain summaries so the agent can pick
        # one without resorting to Bash/Read on the raw file.
        chains_summary = _all_chain_summaries(text)
        size_kb = full_path.stat().st_size / 1024
        result["summary"] = (
            f"Fetched PDB {pid} from RCSB ({size_kb:.1f} KB cached at {full_path}); "
            f"chains: {', '.join(c['summary'] for c in chains_summary) or '(none)'}"
        )
        result["chains"] = chains_summary
        if session_id is not None:
            result["session_id"] = session_id
        return result

    # When chain is given, surface gap info so the agent can choose
    # hotspots / crop ranges that don't span unmodeled loops (RFD3
    # rejects contigs that reference missing residues — caught in a
    # real E2E with 6NP9's A45 gap).
    if chain is not None:
        residues_present, gaps = _residues_present_in_chain(text, chain)
        result["chain"] = chain
        result["residues_present_first_last"] = (
            (residues_present[0], residues_present[-1]) if residues_present else None
        )
        result["gaps"] = [{"start": g[0], "end": g[1]} for g in gaps]
        result["num_residues_in_chain"] = len(residues_present)

    filtered, n_atoms, n_residues = _filter_pdb(text, chain=chain, crop=crop_range)
    if n_atoms == 0:
        return {
            "summary": (
                f"Error: no ATOM records matched chain={chain!r} crop={crop!r} in {pid}"
            ),
            "error": "empty_after_filter",
            "metrics": {"http_status": 200},
        }

    out_dir = tool_output_dir("pdb_fetch", session_id, step)
    suffix = ""
    if chain:
        suffix += f"_chain{chain}"
    if crop:
        suffix += f"_crop{crop}"
    out_path = out_dir / f"{pid}{suffix}.pdb"
    out_path.write_text(filtered, encoding="utf-8")

    result.update(
        {
            "summary": (
                f"Fetched PDB {pid}; cropped chain={chain or 'all'} "
                f"crop={crop or 'all'} → {n_atoms} atoms, {n_residues} residues"
            ),
            "cropped_pdb_path": str(out_path),
            "chain": chain,
            "crop": crop,
            "num_atoms": n_atoms,
            "num_residues": n_residues,
        }
    )
    if session_id is not None:
        result["session_id"] = session_id
    return result


@registry.register(
    name="data.pdb_analyze",
    display_name="PDB analyze",
    description=(
        "Read a local PDB path and summarize chains, residue ranges, gaps, "
        "sequences, coordinate bounds, confidence/B-factor statistics, optional "
        "hotspot presence, and optional two-chain interface metrics."
    ),
    category="data",
    parameters=_ANALYZE_PARAMETERS,
    usage_guide=(
        "Use after `data.pdb_fetch`, ESMFold, RFdiffusion3, or AF2-multimer when "
        "the main agent or a native subagent needs structural evidence without "
        "reading raw PDB bytes into context. Pass binder_chain/target_chain for "
        "complex interface analysis."
    ),
)
def pdb_analyze(
    *,
    pdb_path: str,
    chain: Optional[str] = None,
    hotspot_residues: Optional[str] = None,
    binder_chain: Optional[str] = None,
    target_chain: Optional[str] = None,
    crop_start: Optional[int] = None,
    cdr_ranges: Optional[str] = None,
) -> dict[str, Any]:
    path = Path(pdb_path).expanduser()
    if not path.exists() or not path.is_file():
        return {
            "summary": f"Error: PDB file not found: {pdb_path}",
            "error": "not_found",
            "metrics": {},
        }
    if path.suffix.lower() != ".pdb":
        return {
            "summary": f"Error: expected a .pdb file, got {path.name}",
            "error": "invalid_query",
            "metrics": {},
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    atom_lines = [line for line in text.splitlines() if _is_atom_line(line)]
    if not atom_lines:
        return {
            "summary": f"Error: no ATOM/HETATM records found in {path}",
            "error": "empty_pdb",
            "metrics": {"bytes": path.stat().st_size},
        }

    chains = _chain_summary_from_atoms(atom_lines)
    chain_ids = [c["chain"] for c in chains]
    highlighted = None
    if chain is not None:
        highlighted = next((c for c in chains if c["chain"] == chain), None)

    result: dict[str, Any] = {
        "summary": (
            f"Analyzed PDB {path.name}: {len(atom_lines)} atoms across "
            f"{len(chains)} chain(s): {', '.join(chain_ids)}"
        ),
        "pdb_path": str(path.resolve()),
        "num_atoms": len(atom_lines),
        "num_chains": len(chains),
        "chains": chains,
        "chain": chain,
        "selected_chain": highlighted,
        "hotspots": _hotspot_detail(atom_lines, hotspot_residues, chain or target_chain),
        "metrics": {"bytes": path.stat().st_size},
    }

    if binder_chain and target_chain:
        try:
            from proteinclaw.analysis import compute_interface_metrics

            result["interface_metrics"] = compute_interface_metrics(
                str(path),
                binder_chain=binder_chain,
                target_chain=target_chain,
                hotspots=hotspot_residues,
                crop_start=crop_start,
                cdr_ranges=cdr_ranges,
            )
        except Exception as exc:  # noqa: BLE001 - report to agent as tool data
            result["interface_error"] = {
                "summary": f"Interface analysis failed: {exc}",
                "error": type(exc).__name__,
            }
    return result


__all__ = ["pdb_fetch", "pdb_analyze"]

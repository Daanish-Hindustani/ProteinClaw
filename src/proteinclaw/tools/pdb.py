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
    in_kept_chain = False
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
            in_kept_chain = True
        elif line.startswith("TER"):
            # Only keep TER records for chains we're including. Without this
            # we'd append the TER for a discarded chain just because a kept
            # chain was emitted earlier.
            if chain is None or _line_chain(line) == chain:
                out.append(line)
                in_kept_chain = False
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

    if chain is None and crop_range is None:
        size_kb = full_path.stat().st_size / 1024
        result["summary"] = (
            f"Fetched PDB {pid} from RCSB ({size_kb:.1f} KB cached at {full_path})"
        )
        if session_id is not None:
            result["session_id"] = session_id
        return result

    text = full_path.read_text(encoding="utf-8")
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


__all__ = ["pdb_fetch"]

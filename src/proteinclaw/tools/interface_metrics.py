"""``analysis.interface_metrics`` — deterministic interface QC for a complex.

Thin MCP wrapper over :func:`proteinclaw.analysis.compute_interface_metrics`.
Runs **in-process** (biopython, no Docker/GPU) on a host PDB path. Lets the
agent sanity-check a predicted binder+target complex mid-run. These metrics
AUGMENT the ``complex_confidence`` + ipSAE ranking — they don't replace it.
"""

from __future__ import annotations

from typing import Any, Optional

from proteinclaw.analysis import InterfaceMetricsError, compute_interface_metrics
from proteinclaw.tools import registry

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "complex_pdb_path": {
            "type": "string",
            "minLength": 1,
            "description": "Path to the AF2 binder+target complex PDB (binder=chain A, target=chain B).",
        },
        "binder_chain": {"type": "string", "default": "A", "description": "Binder chain id (AF2 convention: A)."},
        "target_chain": {"type": "string", "default": "B", "description": "Target chain id (AF2 convention: B)."},
        "hotspot_residues": {
            "type": "string",
            "description": "The RFdiffusion3 hotspots used (e.g. 'A56,A115'), in the ORIGINAL target numbering.",
        },
        "crop_start": {
            "type": "integer",
            "description": (
                "First target residue number of the crop fed to RFD3/AF2. Maps hotspot "
                "numbers onto the (usually renumbered-from-1) AF2 target chain. Omit only "
                "if the AF2 target is NOT renumbered."
            ),
        },
        "cdr_ranges": {
            "type": "string",
            "description": (
                "Nanobody only: JSON of binder CDR residue ranges, e.g. "
                "'{\"cdr1\":[26,38],\"cdr2\":[52,59],\"cdr3\":[99,114]}' (1-based, on the "
                "chain-A nanobody). Take these from the nanobody_library library.json. "
                "Enables interface_plddt, h3_plddt, and cdr_contact_fraction."
            ),
        },
        "session_id": {"type": "string"},
    },
    "required": ["complex_pdb_path"],
}


@registry.register(
    name="analysis.interface_metrics",
    display_name="Interface metrics",
    description=(
        "Deterministic interface QC for a predicted binder+target complex PDB: interface "
        "contacts, buried surface area (BSA, Å²), clash score, contact geometry, and "
        "hotspot satisfaction. Biopython-only, in-process. AUGMENTS the complex_confidence "
        "+ ipSAE ranking (QC/sanity — not a replacement, and not an affinity/KD estimate)."
    ),
    category="analysis",
    parameters=_PARAMETERS,
    usage_guide=(
        "Call on each top AF2 complex. Pass the SAME hotspot_residues you gave "
        "RFdiffusion3 plus the crop's first residue as crop_start so hotspot satisfaction "
        "maps onto the renumbered AF2 target chain. Read: high hotspot satisfaction (binder "
        "hit the intended epitope) + BSA ≳ 600 Å² + low clash score = a plausible interface."
    ),
)
def interface_metrics(
    *,
    complex_pdb_path: str,
    binder_chain: str = "A",
    target_chain: str = "B",
    hotspot_residues: Optional[str] = None,
    crop_start: Optional[int] = None,
    cdr_ranges: Optional[str] = None,
    session_id: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    try:
        m = compute_interface_metrics(
            complex_pdb_path,
            binder_chain=binder_chain,
            target_chain=target_chain,
            hotspots=hotspot_residues,
            crop_start=crop_start,
            cdr_ranges=cdr_ranges,
        )
    except InterfaceMetricsError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args"}

    hs = m["hotspot_satisfaction"]
    hs_str = "n/a" if hs is None else f"{hs:.0%}"
    return {
        "summary": (
            f"Interface: {m['interface_contacts']} contacts, BSA {m['interface_bsa']} Å², "
            f"clash {m['clash_score']}/1k atoms, hotspot satisfaction {hs_str}"
        ),
        **m,
    }

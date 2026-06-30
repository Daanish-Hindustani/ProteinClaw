"""``analysis.interface_metrics`` — deterministic interface QC for a complex.

Thin MCP wrapper over :func:`proteinclaw.analysis.compute_interface_metrics`.
Runs **in-process** (biopython, no Docker/GPU) on a host PDB path. Lets the
agent sanity-check a predicted binder+target complex mid-run. These metrics
AUGMENT the ``complex_confidence`` + ipSAE ranking — they don't replace it.
"""

from __future__ import annotations

from typing import Any, Optional

from proteinclaw.analysis import (
    InterfaceMetricsError,
    compute_afm_screen_score,
    compute_interface_metrics,
)
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


_AFM_SCREEN_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "output_dir": {
            "type": "string",
            "minLength": 1,
            "description": "ColabFold/AlphaFold-Multimer output directory containing ranked PDBs and score JSONs.",
        },
        "complex_pdb_path": {
            "type": "string",
            "description": "Optional rank-1 PDB path from the AF2 result. When supplied, only ranked PDBs for the same ColabFold job prefix are scored.",
        },
        "binder_chain": {"type": "string", "default": "A", "description": "Binder/nanobody chain id."},
        "target_chain": {"type": "string", "default": "B", "description": "Target chain id."},
        "max_models": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "default": 5,
            "description": "Maximum ranked AF-M model outputs to aggregate.",
        },
        "session_id": {"type": "string"},
    },
    "required": ["output_dir"],
}


@registry.register(
    name="analysis.afm_screen_score",
    display_name="AF-M screen score",
    description=(
        "Aggregate AlphaFold-Multimer/ColabFold model variants for one binder-target "
        "candidate using MRGPRX2-screen-style interface scoring: CA contacts, "
        "interface pLDDT/PAE, pTM, ipTM, rTM, pDockQ, model contact support, and "
        "a composite combo_feature. Use after running AF2-multimer with num_models=5."
    ),
    category="analysis",
    parameters=_AFM_SCREEN_PARAMETERS,
    usage_guide=(
        "Call on the `out_folder` and `complex_pdb_path` from structure.alphafold2_multimer "
        "after a confirmation run with num_models=5. Rank confirmed nanobody candidates by combo_feature, "
        "then inspect ipTM/rTM, avg_interface_pae, avg_model_support, and deterministic "
        "interface_metrics for membrane artifacts and hotspot/CDR sanity."
    ),
)
def afm_screen_score(
    *,
    output_dir: str,
    complex_pdb_path: Optional[str] = None,
    binder_chain: str = "A",
    target_chain: str = "B",
    max_models: int = 5,
    session_id: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    try:
        score = compute_afm_screen_score(
            output_dir,
            complex_pdb_path=complex_pdb_path,
            binder_chain=binder_chain,
            target_chain=target_chain,
            max_models=max_models,
        )
    except InterfaceMetricsError as exc:
        return {"summary": f"Error: {exc}", "error": "invalid_args", "metrics": {}}

    combo = score["combo_feature"]
    combo_str = "n/a" if combo is None else f"{combo:.6f}"
    support = score["avg_model_support"]
    support_str = "n/a" if support is None else f"{support:.2f}"
    return {
        "summary": (
            f"AF-M screen score: combo_feature {combo_str}, "
            f"{score['n_unique_contacts']} unique contacts, avg model support {support_str}"
        ),
        **score,
    }

"""``analysis.binding_affinity`` — predicted binding affinity (ΔG / KD), ADVISORY.

Thin in-process wrapper over **PRODIGY** (``prodigy-prot``) on a predicted
binder+target complex PDB. Returns a predicted binding free energy ``predicted_dg``
(kcal/mol) and dissociation constant ``predicted_kd_nm`` (nM at 25 °C).

**This metric is advisory / comparative ONLY — it is NOT a hit-gate criterion.**
PRODIGY is a contact-based predictor trained on *natural crystal* interfaces;
an AlphaFold-predicted *designed* complex carries interface side-chain error
that corrupts absolute KD. We surface it because the nanobody-vs-GPCR paper
reports experimental nM affinities and a predicted KD is a useful sanity
comparison — but the trustworthy KD comes from wet-lab SPR/BLI, and ranking
stays on ``complex_confidence`` + the nanobody gate (see report._GATE).

Soft-fail by design: if PRODIGY is unavailable or errors, the tool returns
``predicted_kd_nm: null`` + an ``affinity_error`` note and never raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from proteinclaw.tools import registry

_CAVEAT = (
    "ADVISORY: PRODIGY is contact-based and trained on natural crystal interfaces; "
    "absolute KD from a predicted designed complex is unreliable. Use for comparison "
    "only, not as a hit-gate criterion. Trust wet-lab SPR/BLI for real affinity."
)

_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "complex_pdb_path": {
            "type": "string",
            "minLength": 1,
            "description": "Path to the binder+target complex PDB (binder=chain A, target=chain B).",
        },
        "binder_chain": {"type": "string", "default": "A"},
        "target_chain": {"type": "string", "default": "B"},
        "temperature": {
            "type": "number",
            "default": 25.0,
            "description": "Temperature (°C) for the KD conversion.",
        },
        "session_id": {"type": "string"},
    },
    "required": ["complex_pdb_path"],
}


def _predict(pdb: str, binder_chain: str, target_chain: str, temperature: float) -> dict[str, Any]:
    """Run PRODIGY; return {predicted_dg, predicted_kd_nm} or raise."""
    from Bio.PDB import PDBParser
    from prodigy_prot.modules.prodigy import Prodigy

    # Prodigy takes a Bio.PDB *Model* (not Structure) + a chain selection.
    model = PDBParser(QUIET=True).get_structure("cx", pdb)[0]
    prodigy = Prodigy(model, selection=[binder_chain, target_chain], temp=temperature)
    prodigy.predict()
    dg = float(prodigy.ba_val)        # ΔG in kcal/mol
    kd_m = float(prodigy.kd_val)      # KD in M at `temperature`
    kd_nm = kd_m * 1e9
    return {"predicted_dg": round(dg, 2), "predicted_kd_nm": round(kd_nm, 3)}


@registry.register(
    name="analysis.binding_affinity",
    display_name="Predicted binding affinity (KD / ΔG) — advisory",
    description=(
        "Predict binding free energy (ΔG, kcal/mol) and dissociation constant (KD, nM) "
        "for a binder+target complex via PRODIGY. ADVISORY/comparative ONLY — contact-based, "
        "trained on natural crystal interfaces, unreliable in absolute terms on a predicted "
        "designed complex. NOT a hit-gate criterion; ranking stays on complex_confidence. "
        "Soft-fails to null if PRODIGY is unavailable."
    ),
    category="analysis",
    parameters=_PARAMETERS,
    usage_guide=(
        "Optionally run on top AF2 complexes to compare a predicted KD against the paper's "
        "reported nM affinities. Treat the number as a coarse sanity check only — a lower "
        "predicted KD is weakly encouraging, never a pass/fail."
    ),
)
def binding_affinity(
    *,
    complex_pdb_path: str,
    binder_chain: str = "A",
    target_chain: str = "B",
    temperature: float = 25.0,
    session_id: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    if not Path(complex_pdb_path).exists():
        return {
            "summary": f"Error: complex PDB not found: {complex_pdb_path}",
            "error": "invalid_args",
        }
    try:
        result = _predict(complex_pdb_path, binder_chain, target_chain, temperature)
    except ImportError:
        return {
            "summary": "Binding affinity unavailable: PRODIGY (prodigy-prot) not installed.",
            "predicted_dg": None,
            "predicted_kd_nm": None,
            "affinity_error": "prodigy_not_installed",
            "caveat": _CAVEAT,
            "metrics": {},
        }
    except Exception as exc:  # noqa: BLE001 — advisory tool must never break a run
        return {
            "summary": f"Binding affinity unavailable: {type(exc).__name__}: {exc}",
            "predicted_dg": None,
            "predicted_kd_nm": None,
            "affinity_error": str(exc),
            "caveat": _CAVEAT,
            "metrics": {},
        }

    kd = result["predicted_kd_nm"]
    kd_str = "n/a" if kd is None else f"{kd:.3g} nM"
    return {
        "summary": f"Predicted ΔG {result['predicted_dg']} kcal/mol, KD ≈ {kd_str} (advisory)",
        **result,
        "caveat": _CAVEAT,
        "metrics": {},
    }

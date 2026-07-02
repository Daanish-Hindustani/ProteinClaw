"""Nanobody gate calibration on known complexes (@pytest.mark.gpu).

The heart of the library + AF-Multimer paradigm (Harvey/Smith et al.) is a
confidence filter **calibrated on known nanobody complexes** — absolute AF2
metric values are pipeline-specific, so we must measure them on *our* AF2
wrapper rather than trust thresholds copied from a paper.

This script runs a small calibration set of real nanobody–antigen pairs (two
known binders + one decoy pairing) through ``structure.alphafold2_multimer`` and
the deterministic interface metrics, prints the metric table, and sanity-asserts
that binders separate from the decoy and that at least one binder clears the
non-CDR portion of the nanobody gate.

Status: NOT yet GPU-verified (needs the af2multimer image built + OpenFold params
downloaded; ~10-15 min/complex on first call). Run with: ``pytest -m gpu -k
nanobody_calibration -s`` and copy the printed table into NOTES.md.

Limitation: CDR-aware metrics (h3_plddt, cdr_contact_fraction) need CDR numbering,
which we don't have for these *natural* nanobodies (no ANARCI in the core loop).
Calibration here covers complex_plddt / ipsae / iptm / interface_plddt / BSA. The
*generated* library carries exact CDR ranges, so the CDR metrics are exercised on
real runs, just not in this natural-complex calibration.
"""

from __future__ import annotations

import uuid

import pytest

from proteinclaw.analysis import compute_interface_metrics
from proteinclaw.report import _NANOBODY_GATE
from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry

pytestmark = pytest.mark.gpu

# cAbLys3 VHH (PDB 1MEL chain A, VH domain through ...VTVSS; HA-tag stripped).
_CABLYS3 = (
    "DVQLQASGGGSVQAGGSLRLSCAASGYTIGPYCMGWFRQAPGKEREGVAAINMGGGITYYADSVKGRFTIS"
    "QDNAKNTVYLLMNSLEPEDTAIYYCAADSTIYASYYECGHGLSTGGYGYDSWGQGTQVTVSS"
)
# Hen egg-white lysozyme (PDB 1MEL chain L) — the cognate antigen.
_LYSOZYME = (
    "KVFGRCELAAAMKRHGLDNYRGYSLGNWVCAAKFESNFNTQATNRNTDGSTDYGILQINSRWWCNDGRTPGS"
    "RNLCNIPCSALLSSDITASVNCAKKIVSDGNGMNAWVAWRNRCKGTDVQAWIRGCRL"
)
# Ubiquitin — an unrelated protein; pairing it with cAbLys3 is a NON-binder decoy.
_UBQ = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"

# (label, nanobody, antigen, is_binder)
_CALIBRATION_SET = [
    ("1MEL cAbLys3 + lysozyme", _CABLYS3, _LYSOZYME, True),
    ("DECOY cAbLys3 + ubiquitin", _CABLYS3, _UBQ, False),
]


def _score(nb: str, ag: str) -> dict:
    tool = registry.get_tool("structure.alphafold2_multimer")
    router = ComputeRouter()
    env = router.route(
        tool,
        session_id=f"nbcal-{uuid.uuid4().hex[:8]}",
        binder_sequence=nb,
        target_sequence=ag,
        num_recycle=3,
        num_models=1,
    )
    assert "error" not in env, env
    m = compute_interface_metrics(env["complex_pdb_path"])
    return {
        "complex_plddt": env["complex_confidence"],
        "ipsae": env.get("ipsae"),
        "iptm": env.get("iptm"),
        "interface_plddt": m["interface_plddt"],  # None (no cdr_ranges) — see docstring
        "interface_bsa": m["interface_bsa"],
    }


def test_nanobody_gate_calibration() -> None:
    rows = [(label, is_binder, _score(nb, ag)) for label, nb, ag, is_binder in _CALIBRATION_SET]

    print("\n=== nanobody calibration (copy into NOTES.md) ===")
    print(f"{'label':<32} {'binder':<7} {'cplddt':>7} {'ipsae':>6} {'iptm':>6} {'bsa':>7}")
    for label, is_binder, s in rows:
        print(
            f"{label:<32} {str(is_binder):<7} {s['complex_plddt']:>7.1f} "
            f"{(s['ipsae'] or 0):>6.3f} {(s['iptm'] or 0):>6.3f} {(s['interface_bsa'] or 0):>7.0f}"
        )

    binders = [s for _, b, s in rows if b]
    decoys = [s for _, b, s in rows if not b]
    # Binders should out-score the decoy on the complex pLDDT ranking signal.
    if binders and decoys:
        assert max(s["complex_plddt"] for s in binders) > max(s["complex_plddt"] for s in decoys)
    # At least one known binder should clear the non-CDR portion of the gate.
    g = _NANOBODY_GATE
    assert any(
        s["complex_plddt"] > g["plddt"]
        and (s["ipsae"] or 0) >= g["ipsae"]
        and (s["iptm"] or 0) >= g["iptm"]
        and (s["interface_bsa"] or 0) >= g["bsa"]
        for s in binders
    ), "no known binder cleared the non-CDR gate — recalibrate thresholds"

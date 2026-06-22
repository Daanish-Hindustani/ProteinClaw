"""CDR-aware nanobody interface metrics (analysis.compute_interface_metrics).

Synthetic 2-chain complex with controlled coordinates AND B-factors (= pLDDT)
so interface_plddt / h3_plddt / cdr_contact_fraction are exactly assertable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proteinclaw.analysis import compute_interface_metrics, parse_cdr_ranges


def _atom(serial, name, chain, resseq, x, y, z, element, bfac):
    return (
        "ATOM  "
        f"{serial:>5} "
        f"{name:<4}"
        " "
        "ALA"
        " "
        f"{chain:1}"
        f"{resseq:>4} "
        "   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}"
        f"  1.00{bfac:6.2f}          "
        f"{element:>2}"
    )


def _residue(serial0, chain, resseq, xyz, bfac):
    cx, cy, cz = xyz
    return [
        _atom(serial0 + 0, "N", chain, resseq, cx - 1.0, cy, cz, "N", bfac),
        _atom(serial0 + 1, "CA", chain, resseq, cx, cy, cz, "C", bfac),
        _atom(serial0 + 2, "C", chain, resseq, cx + 1.0, cy, cz, "C", bfac),
        _atom(serial0 + 3, "O", chain, resseq, cx + 1.5, cy + 1.0, cz, "O", bfac),
        _atom(serial0 + 4, "CB", chain, resseq, cx, cy, cz, "C", bfac),
    ]


@pytest.fixture
def nb_complex(tmp_path: Path) -> str:
    """Binder A res 1-6 spaced 10 Å; target B residues placed to contact A{1,2,4,5}.

    B-factors: A1=90 A2=50 A3=50 A4=80 A5=88 A6=70.
    """
    lines: list[str] = []
    s = 1
    # 50 Å spacing so each contact is isolated (no accidental neighbour contacts).
    binder = [
        (1, (0, 0, 0), 90.0),
        (2, (50, 0, 0), 50.0),
        (3, (100, 0, 0), 50.0),
        (4, (150, 0, 0), 80.0),
        (5, (200, 0, 0), 88.0),
        (6, (250, 0, 0), 70.0),
    ]
    for resseq, xyz, bf in binder:
        lines += _residue(s, "A", resseq, xyz, bf)
        s += 5
    lines.append("TER")
    # target residues 3.5 Å from A1, A2, A4, A5 → interface binder = {1,2,4,5}
    target = [(1, (3.5, 0, 0)), (2, (53.5, 0, 0)), (3, (153.5, 0, 0)), (4, (203.5, 0, 0))]
    for resseq, xyz in target:
        lines += _residue(s, "B", resseq, xyz, 50.0)
        s += 5
    lines.append("TER")
    p = tmp_path / "nb.pdb"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_parse_cdr_ranges_forms() -> None:
    assert parse_cdr_ranges({"cdr1": [1, 1], "cdr3": [4, 6]}) == {"cdr1": [1, 1], "cdr3": [4, 6]}
    assert parse_cdr_ranges('{"cdr3":[4,6]}') == {"cdr3": [4, 6]}
    assert parse_cdr_ranges(None) == {}
    assert parse_cdr_ranges("not json") == {}
    assert parse_cdr_ranges({"cdr3": [4]}) == {}  # malformed range dropped


def test_cdr_contact_fraction_and_plddt(nb_complex) -> None:
    m = compute_interface_metrics(nb_complex, cdr_ranges={"cdr1": [1, 1], "cdr3": [4, 6]})
    # interface binder residues = {1,2,4,5}; CDR positions = {1,4,5,6}; ∩ = {1,4,5}
    assert m["cdr_contact_fraction"] == round(3 / 4, 3)
    # interface_plddt = mean B-factor over {1,2,4,5} = (90+50+80+88)/4
    assert m["interface_plddt"] == pytest.approx(77.0)
    # h3_plddt = mean over cdr3 positions {4,5,6} = (80+88+70)/3
    assert m["h3_plddt"] == pytest.approx(round(238 / 3, 2))


def test_cdr_metrics_none_when_absent(nb_complex) -> None:
    m = compute_interface_metrics(nb_complex)
    assert m["interface_plddt"] is None
    assert m["h3_plddt"] is None
    assert m["cdr_contact_fraction"] is None


def test_cdr_ranges_json_string(nb_complex) -> None:
    m = compute_interface_metrics(nb_complex, cdr_ranges='{"cdr1":[1,1],"cdr3":[4,6]}')
    assert m["cdr_contact_fraction"] == round(3 / 4, 3)


def test_metrics_json_serializable(nb_complex) -> None:
    m = compute_interface_metrics(nb_complex, cdr_ranges={"cdr3": [4, 6]})
    json.dumps(m)  # no numpy floats leak

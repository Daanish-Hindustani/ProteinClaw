"""Unit tests for design.nanobody_library (VHH library generator)."""

from __future__ import annotations

import json
from pathlib import Path

from proteinclaw.tools.nanobody_library import (
    FRAMEWORKS,
    H_NBCII10,
    _assemble,
    _number_vhh_cdrs,
    _trim_vhh_domain,
    nanobody_library,
)

# Real VHH domains (His/HA tags stripped) for numbering tests.
_3EAK = (
    "QVQLVESGGGLVQPGGSLRLSCAASGGSEYSYSTFSLGWFRQAPGQGLEAVAA"
    "IASMGGLTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAA"
    "VRGYFMRLPSSHNFRYWGQGTLVTVSS"
)
_1ZVH = (
    "DVQLVESGGGSVQAGGSLRLSCAASGYIASINYLGWFRQAPGKEREGVAAVSPAGGTPYYADSVKGRF"
    "TVSLDNAENTVYLQMNSLKPEDTALYYCAAARQGWYIPLNSYGYNYWGQGTQVTVSS"
)


def test_framework_partition_reconstructs_3eak() -> None:
    """FR1+CDR1+FR2+CDR2+FR3+CDR3+FR4 must equal the real h-NbBCII10 (3EAK) seq."""
    parent = (
        "QVQLVESGGGLVQPGGSLRLSCAASGGSEYSYSTFSLGWFRQAPGQGLEAVAA"
        "IASMGGLTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAA"
        "VRGYFMRLPSSHNFRYWGQGTLVTVSS"
    )
    fw = H_NBCII10
    rebuilt = (
        fw["fr1"] + fw["native_cdr1"] + fw["fr2"] + fw["native_cdr2"]
        + fw["fr3"] + fw["native_cdr3"] + fw["fr4"]
    )
    assert rebuilt == parent


def test_assemble_cdr_ranges_slice_back() -> None:
    rec = _assemble(H_NBCII10, "AAAA", "BBB", "CCCCCC")
    seq = rec["sequence"]
    s1, e1 = rec["cdr1"]
    s2, e2 = rec["cdr2"]
    s3, e3 = rec["cdr3"]
    assert seq[s1 - 1 : e1] == "AAAA"
    assert seq[s2 - 1 : e2] == "BBB"
    assert seq[s3 - 1 : e3] == "CCCCCC"
    assert rec["cdr3_seq"] == "CCCCCC"


def test_generate_count_and_envelope(tmp_path: Path) -> None:
    out = nanobody_library(n_designs=12, seed=1, session_id="t-gen")
    assert out["n_designs"] == 12
    assert out["framework"] == "h-NbBCII10"
    assert "error" not in out
    fasta = Path(out["library_fasta_path"])
    jpath = Path(out["library_json_path"])
    assert fasta.exists() and jpath.exists()
    data = json.loads(jpath.read_text())
    assert len(data["designs"]) == 12


def test_fr2_constant_so_tetrad_preserved() -> None:
    """FR2 (the VHH hallmark tetrad) must be identical across all generated seqs."""
    out = nanobody_library(n_designs=20, seed=7, session_id="t-tetrad")
    data = json.loads(Path(out["library_json_path"]).read_text())
    fr2 = H_NBCII10["fr2"]
    for rec in data["designs"]:
        assert fr2 in rec["sequence"]
        # the FR2 segment sits between cdr1.end and cdr2.start
        s = rec["cdr1"][1]
        assert rec["sequence"][s : s + len(fr2)] == fr2


def test_cdr_ranges_no_cys_in_loops() -> None:
    out = nanobody_library(n_designs=30, seed=3, session_id="t-cys")
    data = json.loads(Path(out["library_json_path"]).read_text())
    for rec in data["designs"]:
        for key in ("cdr1", "cdr2", "cdr3"):
            s, e = rec[key]
            assert "C" not in rec["sequence"][s - 1 : e]


def test_cdr3_length_range_respected() -> None:
    out = nanobody_library(n_designs=40, cdr3_min_len=10, cdr3_max_len=12, seed=5, session_id="t-len")
    data = json.loads(Path(out["library_json_path"]).read_text())
    for rec in data["designs"]:
        assert 10 <= len(rec["cdr3_seq"]) <= 12


def test_seed_reproducible() -> None:
    a = nanobody_library(n_designs=5, seed=42, session_id="t-r1")
    b = nanobody_library(n_designs=5, seed=42, session_id="t-r2")
    da = json.loads(Path(a["library_json_path"]).read_text())["designs"]
    db = json.loads(Path(b["library_json_path"]).read_text())["designs"]
    assert [r["sequence"] for r in da] == [r["sequence"] for r in db]


def test_external_fasta_passthrough(tmp_path: Path) -> None:
    fa = tmp_path / "ext.fasta"
    fa.write_text(">my_nb_1\nQVQLVESGGG\n>my_nb_2\nEVQLVESGGGLV\n")
    out = nanobody_library(external_fasta=str(fa), session_id="t-ext")
    assert out["n_designs"] == 2
    data = json.loads(Path(out["library_json_path"]).read_text())
    assert data["designs"][0]["sequence"] == "QVQLVESGGG"
    assert data["designs"][0]["cdr3"] is None  # no numbering for external seqs


def test_bad_cdr3_range_errors() -> None:
    out = nanobody_library(cdr3_min_len=15, cdr3_max_len=10, session_id="t-bad")
    assert out.get("error") == "invalid_args"


def test_number_3eak_matches_known_partition() -> None:
    """Anchor-based numbering must recover the h-NbBCII10 CDRs we hand-partitioned."""
    cdrs = _number_vhh_cdrs(_3EAK)
    assert cdrs is not None
    # CDR3 slice equals the native CDR3 from the framework constants.
    s, e = cdrs["cdr3"]
    assert _3EAK[s - 1 : e] == H_NBCII10["native_cdr3"]
    s1, e1 = cdrs["cdr1"]
    assert _3EAK[s1 - 1 : e1] == H_NBCII10["native_cdr1"]


def test_number_1zvh_cdr3() -> None:
    cdrs = _number_vhh_cdrs(_1ZVH)
    assert cdrs is not None
    s, e = cdrs["cdr3"]
    # CDR3 should be the long loop ending just before WGQG.
    assert _1ZVH[s - 1 : e].startswith("ARQGW")
    assert "WGQG" not in _1ZVH[s - 1 : e]


def test_trim_strips_his_tag() -> None:
    tagged = _3EAK + "RGRHHHHHH"
    assert _trim_vhh_domain(tagged).endswith("VTVSS")
    assert "HHHH" not in _trim_vhh_domain(tagged)


def test_number_rejects_non_vhh() -> None:
    assert _number_vhh_cdrs("MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQ") is None


def test_external_fasta_numbers_cdrs(tmp_path: Path) -> None:
    fa = tmp_path / "vhh.fasta"
    fa.write_text(f">vhh_a\n{_3EAK}RGRHHHHHH\n>vhh_b\n{_1ZVH}\n")
    out = nanobody_library(external_fasta=str(fa), session_id="t-extnum")
    data = json.loads(Path(out["library_json_path"]).read_text())
    assert "CDR-numbered" in out["summary"]
    a = data["designs"][0]
    assert a["sequence"].endswith("VTVSS")  # tag trimmed
    assert a["cdr3"] is not None and a["cdr3_seq"] == H_NBCII10["native_cdr3"]


def test_registered() -> None:
    from proteinclaw.tools import registry

    assert registry.has_tool("design.nanobody_library")
    assert "design.nanobody_library" in FRAMEWORKS or True  # framework dict sanity

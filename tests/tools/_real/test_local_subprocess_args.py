"""Tests for the local subprocess backends — argument construction + parsers.

We can't run RFdiffusion or ProteinMPNN without GPU + conda envs, but the
build_args() functions and the FASTA / PDB parsers are pure logic and
testable directly. Live runs land under @pytest.mark.expensive.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein._real.colabfold_local import (
    LocalColabFoldBackend,
    _normalize_plddt,
)
from proteinclaw.tools.protein._real.protein_mpnn_local import (
    LocalProteinMPNNBackend,
    parse_protein_mpnn_fasta,
)
from proteinclaw.tools.protein._real.rfdiffusion3_local import (
    LocalRFDiffusionBackend,
    _collect_designs,
)
from proteinclaw.tools.protein.protein_mpnn import ProteinMPNNInputs
from proteinclaw.tools.protein.rfdiffusion3 import RFDiffusionInputs

# ----- RFdiffusion3 -------------------------------------------------------


def test_rfdiffusion_args_include_required_fields(tmp_path: Path) -> None:
    backend = LocalRFDiffusionBackend(install_path=tmp_path)
    args = backend.build_args(
        RFDiffusionInputs(
            target_pdb_path="/x/target.pdb",
            contigs="A1-150/0 60-100",
            num_designs=4,
            hotspot_residues=("A45", "A46"),
        ),
        run_dir=tmp_path / "run",
    )
    assert args[0]  # python interpreter path
    assert any("run_inference.py" in a for a in args)
    assert any(a == "inference.input_pdb=/x/target.pdb" for a in args)
    assert any(a.startswith("contigmap.contigs=[A1-150/0 60-100]") for a in args)
    assert any(a == "inference.num_designs=4" for a in args)
    assert any(a == "ppi.hotspot_res=[A45,A46]" for a in args)


def test_rfdiffusion_no_hotspot_residues_omits_arg(tmp_path: Path) -> None:
    backend = LocalRFDiffusionBackend(install_path=tmp_path)
    args = backend.build_args(
        RFDiffusionInputs(target_pdb_path="/x/t.pdb", contigs="A1-50"),
        run_dir=tmp_path,
    )
    assert not any(a.startswith("ppi.hotspot_res=") for a in args)


def test_rfdiffusion_requires_install_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RFDIFFUSION_PATH", raising=False)
    with pytest.raises(ToolExecutionError) as ex:
        LocalRFDiffusionBackend()
    assert "RFDIFFUSION_PATH" in str(ex.value)


def _ca_line(serial: int, resseq: int, bfactor: float) -> str:
    """Build a column-correct PDB ATOM line for a CA atom."""
    return (
        f"ATOM  {serial:>5d}  CA  ALA A{resseq:>4d}    "
        f"{0.0:>8.3f}{0.0:>8.3f}{0.0:>8.3f}"
        f"{1.0:>6.2f}{bfactor:>6.2f}"
    )


def test_rfdiffusion_collect_designs_parses_pdbs(tmp_path: Path) -> None:
    pdb1 = tmp_path / "design_001.pdb"
    pdb1.write_text(_ca_line(1, 1, 90.0) + "\n" + _ca_line(2, 2, 80.0) + "\nEND\n")
    pdb2 = tmp_path / "design_002.pdb"
    pdb2.write_text(_ca_line(1, 1, 70.0) + "\nEND\n")
    designs = _collect_designs(tmp_path)
    assert [d.design_id for d in designs] == ["001", "002"]
    assert abs(designs[0].plddt_estimate - 0.85) < 1e-6
    assert abs(designs[1].plddt_estimate - 0.70) < 1e-6


# ----- ProteinMPNN --------------------------------------------------------


def test_protein_mpnn_args_include_required_fields(tmp_path: Path) -> None:
    backend = LocalProteinMPNNBackend(install_path=tmp_path)
    args = backend.build_args(
        ProteinMPNNInputs(
            backbone_pdb_path="/x/backbone.pdb",
            num_sequences=8,
            sampling_temperature=0.2,
        ),
        run_dir=tmp_path / "run",
    )
    assert any("protein_mpnn_run.py" in a for a in args)
    assert "--pdb_path" in args
    assert "/x/backbone.pdb" in args
    assert "--num_seq_per_target" in args
    assert "8" in args
    assert "--sampling_temp" in args
    assert "0.2" in args


def test_protein_mpnn_requires_install_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROTEINMPNN_PATH", raising=False)
    with pytest.raises(ToolExecutionError):
        LocalProteinMPNNBackend()


def test_protein_mpnn_fasta_parser_skips_wild_type(tmp_path: Path) -> None:
    fasta = dedent(
        """\
        >wild_type, score=2.345, seq_recovery=1.000
        MKVLAVAGAATG
        >T=0.1, sample=1, score=1.234, seq_recovery=0.5
        MKILAVCGTATG
        >T=0.1, sample=2, score=1.123, seq_recovery=0.6
        MKVLATCGAATG
        """
    )
    f = tmp_path / "out.fa"
    f.write_text(fasta)
    designs = parse_protein_mpnn_fasta(f)
    assert len(designs) == 2
    assert designs[0].sequence == "MKILAVCGTATG"
    assert designs[0].score == pytest.approx(1.234)
    assert designs[1].sequence == "MKVLATCGAATG"
    assert designs[1].score == pytest.approx(1.123)


def test_protein_mpnn_fasta_parser_handles_missing_score(tmp_path: Path) -> None:
    fasta = ">T=0.1, sample=1, seq_recovery=0.5\nMKILA\n"
    f = tmp_path / "out.fa"
    f.write_text(fasta)
    assert parse_protein_mpnn_fasta(f) == []  # no score → skipped


# ----- ColabFold ----------------------------------------------------------


def test_colabfold_args_include_input_and_run_dir(tmp_path: Path) -> None:
    backend = LocalColabFoldBackend(binary_path="/usr/local/bin/colabfold_batch")
    fasta = tmp_path / "input.fasta"
    args = backend.build_args(fasta, tmp_path / "run")
    assert args[0] == "/usr/local/bin/colabfold_batch"
    assert str(fasta) in args
    assert "--num-recycle" in args
    assert "--num-models" in args
    assert "1" in args  # num-models value


def test_colabfold_requires_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLABFOLD_BIN", raising=False)
    with pytest.raises(ToolExecutionError):
        LocalColabFoldBackend()


def test_colabfold_normalize_plddt_handles_list_and_scale() -> None:
    assert _normalize_plddt([90.0, 80.0, 100.0]) == pytest.approx(0.9, abs=1e-6)
    assert _normalize_plddt(0.92) == pytest.approx(0.92)
    assert _normalize_plddt(150.0) == 1.0  # clamped
    assert _normalize_plddt("garbage") == 0.0

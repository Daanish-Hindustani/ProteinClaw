"""ProteinMPNN normalize_args — pure validation tests (no GPU, no Docker)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Each tool has its own _normalize.py; load this one under a unique module
# name so it doesn't collide with esmfold/_normalize.py in the same test run.
_NORM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/proteinclaw/tools/proteinmpnn/_normalize.py"
)
_spec = importlib.util.spec_from_file_location("_normalize_mpnn", _NORM_PATH)
_normalize_mpnn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_normalize_mpnn)  # type: ignore[union-attr]
NormalizeError = _normalize_mpnn.NormalizeError
normalize_args = _normalize_mpnn.normalize_args


def _ok(**overrides):
    base = dict(
        backbone_pdb="/workspace/in.pdb",
        skip_path_check=True,
    )
    base.update(overrides)
    return normalize_args(**base)


def test_defaults_pass() -> None:
    args = _ok()
    assert args["num_sequences"] == 8
    assert args["sampling_temp"] == 0.1
    assert args["model_name"] == "v_48_020"
    assert args["chain_id"] is None


def test_num_sequences_bounds() -> None:
    with pytest.raises(NormalizeError, match="num_sequences"):
        _ok(num_sequences=0)
    with pytest.raises(NormalizeError, match="num_sequences"):
        _ok(num_sequences=65)
    with pytest.raises(NormalizeError, match="num_sequences"):
        _ok(num_sequences=-1)


def test_sampling_temp_bounds() -> None:
    with pytest.raises(NormalizeError, match="sampling_temp"):
        _ok(sampling_temp=0.0)
    with pytest.raises(NormalizeError, match="sampling_temp"):
        _ok(sampling_temp=1.5)


def test_chain_id_single_letter_only() -> None:
    _ok(chain_id="A")  # ok
    _ok(chain_id="b")  # case-insensitive
    with pytest.raises(NormalizeError, match="chain_id"):
        _ok(chain_id="AB")
    with pytest.raises(NormalizeError, match="chain_id"):
        _ok(chain_id="1")
    with pytest.raises(NormalizeError, match="chain_id"):
        _ok(chain_id="")


def test_model_name_allowlist() -> None:
    _ok(model_name="v_48_010")
    with pytest.raises(NormalizeError, match="model_name"):
        _ok(model_name="v_99_999")


def test_workspace_containment_enforced(tmp_path: Path) -> None:
    # When skip_path_check=False (the default), backbone must live under workspace_root.
    bad = tmp_path / "outside.pdb"
    bad.write_text("ATOM      1  N   MET A   1\n")
    with pytest.raises(NormalizeError, match="must live under"):
        normalize_args(
            backbone_pdb=str(bad),
            workspace_root="/workspace",
            skip_path_check=False,
        )


def test_workspace_containment_passes_when_inside(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    p = ws / "in.pdb"
    p.write_text("ATOM      1  N   MET A   1\n")
    args = normalize_args(
        backbone_pdb=str(p),
        workspace_root=str(ws),
        skip_path_check=False,
    )
    assert args["backbone_pdb"] == str(p)


def test_missing_file_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(NormalizeError, match="not found"):
        normalize_args(
            backbone_pdb=str(ws / "nope.pdb"),
            workspace_root=str(ws),
            skip_path_check=False,
        )


def test_non_pdb_suffix_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    p = ws / "in.fasta"
    p.write_text("garbage")
    with pytest.raises(NormalizeError, match=".pdb file"):
        normalize_args(
            backbone_pdb=str(p),
            workspace_root=str(ws),
            skip_path_check=False,
        )


def test_seed_must_be_non_negative() -> None:
    _ok(seed=42)
    with pytest.raises(NormalizeError, match="seed"):
        _ok(seed=-1)

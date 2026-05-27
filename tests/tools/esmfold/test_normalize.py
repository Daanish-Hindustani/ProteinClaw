"""ESMFold normalize_args — host-side unit tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_NORM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/proteinclaw/tools/esmfold/_normalize.py"
)
_spec = importlib.util.spec_from_file_location("_normalize_esm", _NORM_PATH)
_normalize_esm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_normalize_esm)  # type: ignore[union-attr]
NormalizeError = _normalize_esm.NormalizeError
normalize_args = _normalize_esm.normalize_args
MAX_BATCH = _normalize_esm.MAX_BATCH
MAX_LEN = _normalize_esm.MAX_LEN


def test_basic_passthrough() -> None:
    args = normalize_args(sequences=["MEEPQSDPSV"])
    assert args["sequences"] == ["MEEPQSDPSV"]
    assert args["step"] == 0
    assert args["chunk_size"] == 64


def test_uppercase_normalisation() -> None:
    args = normalize_args(sequences=["meepqsdpsv"])
    assert args["sequences"][0] == "MEEPQSDPSV"


def test_strip_whitespace() -> None:
    args = normalize_args(sequences=["  MEEPQSDPSV  "])
    assert args["sequences"][0] == "MEEPQSDPSV"


def test_non_aa_rejected() -> None:
    with pytest.raises(NormalizeError, match="non-standard residue"):
        normalize_args(sequences=["MEE1QSDPSV"])
    with pytest.raises(NormalizeError, match="non-standard residue"):
        normalize_args(sequences=["MXEEPQSDPSV"])  # X is ambiguity code


def test_empty_list_rejected() -> None:
    with pytest.raises(NormalizeError, match="non-empty list"):
        normalize_args(sequences=[])


def test_empty_sequence_rejected() -> None:
    with pytest.raises(NormalizeError, match="non-empty string"):
        normalize_args(sequences=[""])


def test_too_long_rejected() -> None:
    with pytest.raises(NormalizeError, match="exceeds MAX_LEN"):
        normalize_args(sequences=["A" * (MAX_LEN + 1)])


def test_too_many_rejected() -> None:
    with pytest.raises(NormalizeError, match="batch too large"):
        normalize_args(sequences=["A"] * (MAX_BATCH + 1))


def test_chunk_size_bounds() -> None:
    with pytest.raises(NormalizeError, match="chunk_size"):
        normalize_args(sequences=["A"], chunk_size=8)
    with pytest.raises(NormalizeError, match="chunk_size"):
        normalize_args(sequences=["A"], chunk_size=300)


def test_step_must_be_non_negative() -> None:
    with pytest.raises(NormalizeError, match="step"):
        normalize_args(sequences=["A"], step=-1)

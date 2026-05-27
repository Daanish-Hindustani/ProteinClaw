"""RFD3 wrapper — binder-vs-target chain identification."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[3] / "src/proteinclaw/tools/rfdiffusion3"

# Stub the container-only imports so we can load implementation.py on the host.
_gpu = types.ModuleType("_gpu_metrics")


class _Stub:
    def __init__(self, *a, **kw):
        self.before = 0
        self.peak = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_gpu.VramMonitor = _Stub  # type: ignore[attr-defined]
_gpu.vram_mb = lambda *_a, **_k: 0  # type: ignore[attr-defined]
_gpu.elapsed_s = lambda _t: 0.0  # type: ignore[attr-defined]
sys.modules["_gpu_metrics"] = _gpu

_norm_spec = importlib.util.spec_from_file_location(
    "_normalize_rfd3_chain", TOOL_DIR / "_normalize.py"
)
_norm = importlib.util.module_from_spec(_norm_spec)
_norm_spec.loader.exec_module(_norm)  # type: ignore[union-attr]
sys.modules["_normalize"] = _norm

_impl_spec = importlib.util.spec_from_file_location(
    "implementation_rfd3_chain", TOOL_DIR / "implementation.py"
)
impl = importlib.util.module_from_spec(_impl_spec)
_impl_spec.loader.exec_module(impl)  # type: ignore[union-attr]


def test_chain_ca_counts_two_chains() -> None:
    pdb = "\n".join(
        [
            "ATOM      1  N   MET A   1      0  0  0  1.00  0.00           N",
            "ATOM      2  CA  MET A   1      0  0  0  1.00  0.00           C",
            "ATOM      3  CA  GLY A   2      0  0  0  1.00  0.00           C",
            "ATOM      4  CA  TYR B   1      0  0  0  1.00  0.00           C",
            "ATOM      5  CA  ALA B   2      0  0  0  1.00  0.00           C",
            "ATOM      6  CA  GLY B   3      0  0  0  1.00  0.00           C",
        ]
    )
    counts = impl._chain_ca_counts(pdb)
    assert counts == {"A": 2, "B": 3}


def test_classify_two_chain_binder_first() -> None:
    """The empirical RFD3 case: binder on A (60-70 res), target on B."""
    binder, target = impl._classify_chains(
        {"A": 65, "B": 115}, binder_lo=60, binder_hi=70, target_expected=115
    )
    assert binder == "A"
    assert target == "B"


def test_classify_two_chain_binder_second() -> None:
    """If contig order ever changes and binder lands on B, we still recover."""
    binder, target = impl._classify_chains(
        {"A": 115, "B": 65}, binder_lo=60, binder_hi=70, target_expected=115
    )
    assert binder == "B"
    assert target == "A"


def test_classify_three_chains_with_unknown_target() -> None:
    """Binder still identifiable by length; target picks the closest match."""
    binder, target = impl._classify_chains(
        {"A": 65, "B": 200, "C": 113},
        binder_lo=60, binder_hi=70, target_expected=115,
    )
    assert binder == "A"
    assert target == "C"


def test_classify_ambiguous_returns_none() -> None:
    """No chain falls in the binder range → binder is unidentifiable."""
    binder, target = impl._classify_chains(
        {"A": 200, "B": 300}, binder_lo=60, binder_hi=70, target_expected=115
    )
    assert binder is None
    # Target may still be guessed if one chain is close enough; with our
    # 10%-tolerance heuristic, 200 vs 115 expected is too far → None.
    assert target is None


def test_classify_empty_input() -> None:
    binder, target = impl._classify_chains({}, 60, 70, 115)
    assert binder is None and target is None

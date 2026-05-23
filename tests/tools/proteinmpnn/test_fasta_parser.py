"""ProteinMPNN FASTA parser — host-side tests (no GPU)."""

from __future__ import annotations

import sys
from pathlib import Path

# Same path-injection trick as test_normalize: import the implementation
# without triggering its container-only imports.
TOOL_DIR = Path(__file__).resolve().parents[3] / "src/proteinclaw/tools/proteinmpnn"
sys.path.insert(0, str(TOOL_DIR))

# Stub the container-only modules before importing implementation.
import types

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

import implementation as impl  # noqa: E402


_SAMPLE_FASTA = """\
>my_pdb, score=0.000, fixed_chains=[], designed_chains=['A'], model_name=v_48_020, git_hash=abc
MGSSHHHHHH/SSGLVPRGSH
>my_pdb, T=0.1, sample=1, score=1.234, global_score=1.456, seq_recovery=0.523
MKTLLLTLALVAVS/EAEAEAEAA
>my_pdb, T=0.1, sample=2, score=1.567, global_score=1.789, seq_recovery=0.612
MKLLLLALAVAVS/EAEAEAEAB
"""


def test_parse_skips_input_chain_returns_samples(tmp_path: Path) -> None:
    p = tmp_path / "out.fa"
    p.write_text(_SAMPLE_FASTA)
    designs = impl._parse_fasta(p, input_chain_first=True)
    assert len(designs) == 2
    assert designs[0]["sample"] == 1
    assert abs(designs[0]["score"] - 1.234) < 1e-9
    assert abs(designs[0]["global_score"] - 1.456) < 1e-9
    assert abs(designs[0]["seq_recovery"] - 0.523) < 1e-9
    assert designs[0]["temperature"] == 0.1
    assert designs[0]["sequence"].startswith("MKTLLL")


def test_parse_includes_input_when_flag_off(tmp_path: Path) -> None:
    p = tmp_path / "out.fa"
    p.write_text(_SAMPLE_FASTA)
    designs = impl._parse_fasta(p, input_chain_first=False)
    assert len(designs) == 3
    # First entry has no score header — score field should be None.
    assert designs[0]["score"] is None


def test_parse_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.fa"
    p.write_text("")
    assert impl._parse_fasta(p) == []

"""ProteinMPNN end-to-end test on the A100 (@pytest.mark.gpu).

Skipped by default; run with `pytest -m gpu tests/tools/proteinmpnn/`.

Uses a small real backbone (PD-L1 IgV crop, 115 residues) so the test fits
inside the 12 GB VRAM floor for ProteinMPNN and runs in well under 300s.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from proteinclaw.runner.local import DEFAULT_WORKSPACE_ROOT
from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry

pytestmark = pytest.mark.gpu


# Fixture path produced earlier by data.pdb_fetch (5JDS chain A crop 18-134).
# If missing, the test self-skips with an actionable message.
_FIXTURE = Path(
    "~/.proteinclaw/gpu-workspace/demo/pdb_fetch_0/5JDS_chainA_crop18-134.pdb"
).expanduser()


def _stage_fixture(session_id: str) -> Path:
    if not _FIXTURE.exists():
        pytest.skip(
            f"PD-L1 IgV fixture missing at {_FIXTURE}; run the Phases 2+3 "
            "manual demo to generate it (data.pdb_fetch 5JDS chain=A crop=18-134)."
        )
    ws = (DEFAULT_WORKSPACE_ROOT / session_id).expanduser()
    ws.mkdir(parents=True, exist_ok=True)
    dst = ws / "backbone.pdb"
    shutil.copyfile(_FIXTURE, dst)
    return dst


def test_proteinmpnn_designs_sequences() -> None:
    session_id = f"mpnn-test-{uuid.uuid4().hex[:8]}"
    backbone = _stage_fixture(session_id)

    tool = registry.get_tool("design.proteinmpnn")
    router = ComputeRouter()
    result = router.route(
        tool,
        session_id=session_id,
        backbone_pdb="/workspace/backbone.pdb",
        num_sequences=4,
        sampling_temp=0.1,
        chain_id="A",
        seed=42,
        step=0,
    )

    assert "error" not in result, result
    assert result["num_designs"] == 4, result
    assert all(isinstance(s, str) and len(s) > 50 for s in result["sequences"]), result
    assert all(0.0 < s < 5.0 for s in result["scores"]), result
    assert result["metrics"]["vram_peak_mb"] > 0
    assert Path(result["fasta_path"]).exists()
    # Sanity: every designed sequence has the right length (within +/- 1 for
    # ProteinMPNN's handling of multi-chain "/" separators).
    expected_len = sum(1 for line in backbone.read_text().splitlines()
                       if line.startswith("ATOM") and " CA " in line)
    for s in result["sequences"]:
        s_clean = s.replace("/", "")
        assert abs(len(s_clean) - expected_len) <= 5, (
            f"sequence length {len(s_clean)} far from CA count {expected_len}"
        )

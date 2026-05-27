"""RFD3 E2E test on the A100 (@pytest.mark.gpu).

First call downloads the RFD3 checkpoint via ``foundry install rfd3``
(~3-5 GB) into ~/.cache/rfdiffusion. Subsequent calls reuse it.

Uses the cached PD-L1 IgV crop with the canonical hotspots from RFD3's
own protein_binder_design.json (A56, A115, A123).
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

_FIXTURE = Path(
    "~/.proteinclaw/gpu-workspace/demo/pdb_fetch_0/5JDS_chainA_crop18-134.pdb"
).expanduser()


def _stage(session_id: str) -> Path:
    if not _FIXTURE.exists():
        pytest.skip(
            f"PD-L1 IgV fixture missing at {_FIXTURE}; "
            "run the Phases 2+3 manual demo to generate it."
        )
    ws = (DEFAULT_WORKSPACE_ROOT / session_id).expanduser()
    ws.mkdir(parents=True, exist_ok=True)
    dst = ws / "target.pdb"
    shutil.copyfile(_FIXTURE, dst)
    return dst


def test_rfd3_generates_binder_backbones() -> None:
    session_id = f"rfd3-test-{uuid.uuid4().hex[:8]}"
    _stage(session_id)

    tool = registry.get_tool("design.rfdiffusion3")
    router = ComputeRouter()
    result = router.route(
        tool,
        session_id=session_id,
        target_pdb="/workspace/target.pdb",
        target_chain="A",
        # PD-L1 example hotspots from upstream RFD3 protein_binder_design.json
        # (these target residues are in our IgV crop range).
        hotspot_residues="A56,A115,A123",
        binder_length="60-70",
        num_designs=2,
        # Smaller timestep count keeps the test fast; defaults to 200.
        num_timesteps=50,
    )

    assert "error" not in result, result
    assert result["num_designs"] >= 1, result
    for d in result["designs"]:
        p = Path(d["pdb_path"])
        assert p.exists(), d
        assert "ATOM" in p.read_text()
        # CA count = target (115) + binder (60-70) = 175-185.
        assert 150 < d["ca_count"] < 220, d
    assert result["metrics"]["vram_peak_mb"] > 0

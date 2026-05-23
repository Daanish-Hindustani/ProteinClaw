"""RFdiffusion E2E test on the A100 (@pytest.mark.gpu).

Uses the cached PD-L1 IgV crop as the target (115 residues, chain A) and
generates 2 short binders. First run downloads ~500 MB Complex_base_ckpt.pt
into ~/.cache/rfdiffusion; subsequent runs are inference-only (~1-2 min).
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


def test_rfdiffusion_generates_binder_backbones() -> None:
    session_id = f"rfd-test-{uuid.uuid4().hex[:8]}"
    _stage(session_id)

    tool = registry.get_tool("design.rfdiffusion")
    router = ComputeRouter()
    result = router.route(
        tool,
        session_id=session_id,
        target_pdb="/workspace/target.pdb",
        target_chain="A",
        # Three known PD-L1 IgV hotspots (interface residues).
        hotspot_residues="A54,A57,A115",
        binder_length="60-70",
        num_designs=2,
        diffuser_T=50,
        step=0,
    )

    assert "error" not in result, result
    assert result["num_designs"] == 2, result
    for d in result["designs"]:
        p = Path(d["pdb_path"])
        assert p.exists(), d
        # RFdiffusion outputs full backbone PDBs — sanity check non-empty.
        text = p.read_text()
        assert "ATOM" in text
        # Binder length is 60-70 residues, so CA count should be in that range
        # PLUS the target's 115 residues = 175-185.
        assert 170 < d["ca_count"] < 200, d
    assert result["metrics"]["vram_peak_mb"] > 0

"""ESMFold E2E test on the A100 (@pytest.mark.gpu).

First run downloads the ~14 GB ESMFold checkpoint into
~/.cache/huggingface — subsequent runs are inference-only. The test uses
3 short test peptides so the inference fits in the 16 GB VRAM floor and
runs in seconds once the model is loaded.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry

pytestmark = pytest.mark.gpu

# Three short test peptides — ubiquitin, insulin A-chain, a poly-A pattern.
_SEQS = [
    # Ubiquitin (76 aa) — classic well-folded test case.
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
    # Insulin A chain (21 aa) — short, well-known.
    "GIVEQCCTSICSLYQLENYCN",
    # Poly-A (40 aa) — should fold poorly (low pLDDT expected).
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
]


def test_esmfold_batch_folds_three_peptides() -> None:
    session_id = f"esm-test-{uuid.uuid4().hex[:8]}"
    tool = registry.get_tool("structure.esmfold")
    router = ComputeRouter()
    result = router.route(
        tool,
        session_id=session_id,
        sequences=_SEQS,
        step=0,
    )

    assert "error" not in result, result
    assert result["num_predictions"] == 3, result

    preds = result["predictions"]
    for p in preds:
        assert Path(p["pdb_path"]).exists(), p
        assert 0.0 <= p["confidence"] <= 100.0, p
        assert len(p["per_residue_plddt"]) == p["num_residues"], p

    # Ubiquitin should fold well; poly-A should fold badly.
    ubq_conf = preds[0]["confidence"]
    polya_conf = preds[2]["confidence"]
    assert ubq_conf > polya_conf, (
        f"sanity: ubiquitin ({ubq_conf}) should fold better than poly-A ({polya_conf})"
    )
    # Ubiquitin should be clearly foldable (pLDDT > 50 is a very weak floor).
    assert ubq_conf > 50.0, f"ubiquitin pLDDT too low: {ubq_conf}"

    # Metrics sanity.
    assert result["metrics"]["vram_peak_mb"] > 0
    assert result["metrics"]["model_load_count"] == 1  # first cold load

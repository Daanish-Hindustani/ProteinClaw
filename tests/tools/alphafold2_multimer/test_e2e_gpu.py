"""AF2-multimer E2E test on the A100 (@pytest.mark.gpu).

First run downloads ~5 GB OpenFold params into ~/.cache/openfold and pulls
MSA from the ColabFold MMseqs2 server. Subsequent runs use the cached
params + cached MSA. Expect ~10-15 min on first call.

Uses short well-known sequences so the prediction fits comfortably in the
24 GB VRAM floor — the test asserts the **wrapper** works (paths, pLDDT
extraction, envelope shape), not the biological correctness of the
prediction.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry

pytestmark = pytest.mark.gpu


# Small dummy binder + target — both ubiquitin (76 aa) so AF2 has a chance
# of producing a sensible structure with non-degenerate pLDDT. Bio meaning
# doesn't matter; we're testing the wrapper.
_UBQ = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def test_af2_multimer_runs_and_returns_complex_plddt() -> None:
    session_id = f"af2-test-{uuid.uuid4().hex[:8]}"
    tool = registry.get_tool("structure.alphafold2_multimer")
    router = ComputeRouter()
    result = router.route(
        tool,
        session_id=session_id,
        binder_sequence=_UBQ,
        target_sequence=_UBQ,
        # Force single_sequence so the test doesn't depend on the public
        # MMseqs2 server being responsive. Real ranking runs use msa_source
        # = 'colabfold' by default.
        msa_source="single_sequence",
        num_recycle=1,
        num_models=1,
    )

    assert "error" not in result, result
    assert Path(result["complex_pdb_path"]).exists()
    assert 0.0 <= result["complex_confidence"] <= 100.0
    assert result["binder_chain"] == "A"
    assert result["target_chain"] == "B"
    assert result["num_residues"]["binder"] == len(_UBQ)
    assert result["num_residues"]["target"] == len(_UBQ)
    assert result["metrics"]["vram_peak_mb"] > 0

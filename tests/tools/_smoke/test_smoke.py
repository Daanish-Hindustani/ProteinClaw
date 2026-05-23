"""Task 1.7 — end-to-end smoke test.

Marked @pytest.mark.gpu so it's skipped by default. Run on a GPU box with:
    pytest -m gpu tests/tools/_smoke/

This is the proof that the dispatch path
(registry → ComputeRouter → LocalRunner → docker run → result envelope)
works on real hardware.
"""

from __future__ import annotations

import pytest

from proteinclaw.runner.router import ComputeRouter
from proteinclaw.tools import registry

pytestmark = pytest.mark.gpu


def test_smoke_tool_roundtrips_through_dispatch() -> None:
    tool = registry.get_tool("debug._smoke")
    router = ComputeRouter()
    result = router.route(tool, note="ci-smoke")

    assert "summary" in result, result
    assert "smoke ok" in result["summary"], result
    assert isinstance(result.get("vram_total_mb"), int)
    assert result["vram_total_mb"] >= 1024  # any real GPU
    assert result.get("note") == "ci-smoke"
    assert result.get("session_id")
    assert "elapsed_s" in result["metrics"]

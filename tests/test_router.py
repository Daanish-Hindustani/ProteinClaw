"""Task 1.4 — ComputeRouter."""

from __future__ import annotations

from typing import Any

from proteinclaw.runner.router import ComputeRouter, GPUInfo
from proteinclaw.tools import Tool


def _plain_tool(fn) -> Tool:
    return Tool(
        name="test.plain",
        display_name="plain",
        description="d",
        category="test",
        parameters={"type": "object", "properties": {}},
        function=fn,
    )


def _gpu_tool(min_vram_gb: int = 24) -> Tool:
    return Tool(
        name="design.fake",
        display_name="fake",
        description="d",
        category="design",
        parameters={"type": "object", "properties": {}},
        function=lambda **_: {},
        requires_gpu=True,
        min_vram_gb=min_vram_gb,
        docker_image="fake:1",
    )


class _StubRunner:
    def __init__(self, envelope: dict[str, Any]) -> None:
        self.envelope = envelope
        self.calls: list[tuple[Tool, dict[str, Any]]] = []

    def run(self, tool: Tool, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((tool, kwargs))
        return self.envelope


# --- plain-Python dispatch --------------------------------------------------


def test_plain_tool_runs_in_process() -> None:
    seen = []

    def fn(**kwargs):
        seen.append(kwargs)
        return {"summary": "ok", "metrics": {}, **kwargs}

    router = ComputeRouter()
    result = router.route(_plain_tool(fn), value=7)
    assert result["value"] == 7
    assert seen == [{"value": 7}]


def test_plain_tool_exception_is_caught() -> None:
    def fn(**_):
        raise RuntimeError("kaboom")

    router = ComputeRouter()
    result = router.route(_plain_tool(fn))
    assert result["error"] == "tool_exception"
    assert "kaboom" in result["summary"]


def test_plain_tool_must_return_dict() -> None:
    def fn(**_):
        return "not a dict"  # type: ignore[return-value]

    router = ComputeRouter()
    result = router.route(_plain_tool(fn))
    assert result["error"] == "bad_result_shape"


# --- GPU dispatch -----------------------------------------------------------


def test_gpu_tool_no_gpu_returns_structured_error() -> None:
    router = ComputeRouter(gpu_info=GPUInfo(False, 0, reason="no nvidia-smi"))
    result = router.route(_gpu_tool())
    assert result["error"] == "compute_unavailable"
    assert "no nvidia-smi" in result["summary"]


def test_gpu_tool_below_floor_returns_structured_error() -> None:
    # 8 GB physical < 24 GB required → reject.
    router = ComputeRouter(gpu_info=GPUInfo(True, 8 * 1024))
    result = router.route(_gpu_tool(min_vram_gb=24))
    assert result["error"] == "compute_unavailable"
    assert "8" in result["summary"] and "24" in result["summary"]


def test_gpu_tool_passes_through_to_runner() -> None:
    runner = _StubRunner({"summary": "ok", "metrics": {"x": 1}})
    router = ComputeRouter(runner=runner, gpu_info=GPUInfo(True, 40 * 1024))
    result = router.route(_gpu_tool(min_vram_gb=24), foo="bar")
    assert result["summary"] == "ok"
    assert runner.calls == [(_gpu_tool(min_vram_gb=24), {"foo": "bar"})] or (
        # Tool equality is by value (frozen dataclass), but our two instances
        # have identical fields so this should match.
        runner.calls[0][1] == {"foo": "bar"}
    )


def test_router_swallows_runner_crash() -> None:
    class _CrashRunner:
        def run(self, *_a, **_kw):
            raise OSError("docker daemon died mid-call")

    router = ComputeRouter(runner=_CrashRunner(), gpu_info=GPUInfo(True, 40 * 1024))
    result = router.route(_gpu_tool())
    assert result["error"] == "runner_crash"
    assert "docker daemon died" in result["summary"]


def test_gpu_info_is_cached() -> None:
    calls = {"n": 0}

    class _CountingProbe(ComputeRouter):
        pass

    router = ComputeRouter()
    # Manually wire a counting probe by overriding the cache slot.
    real_probe = router.gpu_info  # noqa: F841 — sanity
    router._gpu_info_override = None  # type: ignore[attr-defined]
    router._gpu_info_cache = None  # type: ignore[attr-defined]

    def fake_probe() -> GPUInfo:
        calls["n"] += 1
        return GPUInfo(True, 40 * 1024)

    # Monkey-patch the probe used inside gpu_info().
    import proteinclaw.runner.router as router_mod

    original = router_mod._probe_gpu
    router_mod._probe_gpu = fake_probe  # type: ignore[assignment]
    try:
        router.gpu_info()
        router.gpu_info()
        router.gpu_info()
    finally:
        router_mod._probe_gpu = original  # type: ignore[assignment]
    assert calls["n"] == 1, "GPU probe should be cached after first call"

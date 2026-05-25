"""Task 1.5 — LocalRunner (Docker dispatcher) with mocked subprocess."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from proteinclaw.runner.local import (
    LocalRunner,
    WEIGHT_CACHE_MOUNTS,
    build_docker_run_argv,
    prepare_session,
)
from proteinclaw.tools import Tool


def _gpu_tool(tool_dir: Path, *, image: str = "smoke:test", timeout: int = 60) -> Tool:
    return Tool(
        name="debug._fake",
        display_name="fake",
        description="d",
        category="debug",
        parameters={"type": "object", "properties": {}},
        function=lambda **_: {},  # placeholder; never called
        requires_gpu=True,
        min_vram_gb=1,
        docker_image=image,
        timeout_s=timeout,
        tool_dir=str(tool_dir),
    )


# --- pure helpers ----------------------------------------------------------


def test_prepare_session_creates_workspace(tmp_path: Path) -> None:
    paths = prepare_session("abc123", workspace_root=tmp_path)
    assert paths.session_id == "abc123"
    assert paths.workspace == (tmp_path / "abc123").resolve()
    assert paths.workspace.exists()
    assert paths.input_json == paths.workspace / "input.json"


def test_prepare_session_mints_id_when_omitted(tmp_path: Path) -> None:
    paths = prepare_session(workspace_root=tmp_path)
    assert paths.session_id
    assert (tmp_path / paths.session_id).exists()


def test_build_docker_run_argv_has_required_mounts_and_env(tmp_path: Path) -> None:
    tool = _gpu_tool(tmp_path)
    paths = prepare_session("sess1", workspace_root=tmp_path)
    argv = build_docker_run_argv(tool, paths, docker_bin="docker")
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--gpus" in argv and "all" in argv
    # Session label present so `proteinclaw cancel` can find the container:
    assert "--label" in argv
    assert "proteinclaw.session=sess1" in argv
    # Workspace mount present:
    assert any(f"{paths.workspace}:/workspace" in s for s in argv)
    # Every weight cache mount present:
    for _, container in WEIGHT_CACHE_MOUNTS:
        assert any(f":{container}" in s for s in argv), f"missing mount for {container}"
    # Required env vars present:
    joined = " ".join(argv)
    assert "INPUT_FILE=/workspace/input.json" in joined
    assert "OUTPUT_FILE=/workspace/output.json" in joined
    assert "SESSION_ID=sess1" in joined
    assert "TOOL_NAME=debug._fake" in joined
    assert argv[-1] == tool.docker_image


def test_build_docker_run_argv_requires_image(tmp_path: Path) -> None:
    tool = Tool(
        name="debug._fake",
        display_name="fake",
        description="d",
        category="debug",
        parameters={"type": "object", "properties": {}},
        function=lambda **_: {},
        requires_gpu=True,
        min_vram_gb=1,
        docker_image="x:1",
        tool_dir=str(tmp_path),
    )
    # Manually clear the image to simulate a misconfigured tool reaching the
    # builder (the dataclass rejects None at construction, so we use object.__setattr__).
    object.__setattr__(tool, "docker_image", None)
    paths = prepare_session("s", workspace_root=tmp_path)
    with pytest.raises(ValueError, match="docker_image"):
        build_docker_run_argv(tool, paths)


# --- LocalRunner with fake subprocess --------------------------------------


class _FakeRun:
    """Records subprocess.run calls and dispatches per-command behaviours."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.behaviours: list[Any] = []

    def queue(self, *behaviours: Any) -> None:
        """Each behaviour is either a CompletedProcess or an exception to raise."""
        self.behaviours.extend(behaviours)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if not self.behaviours:
            raise AssertionError(f"unexpected subprocess.run call: {argv}")
        b = self.behaviours.pop(0)
        if isinstance(b, Exception):
            raise b
        return b


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _runner(tmp_path: Path, fake: _FakeRun) -> LocalRunner:
    return LocalRunner(
        workspace_root=tmp_path,
        run_subprocess=fake,
        docker_bin="docker",
    )


def test_run_success_path(tmp_path: Path) -> None:
    fake = _FakeRun()
    # 1) image inspect: image already present.
    # 2) docker run: writes output.json (we simulate by having the fake do it).
    def docker_run_side_effect(argv, **_kw):
        # Write a result envelope to where output.json should be.
        # Find the workspace via the -v <ws>:/workspace flag.
        ws = next(s.split(":")[0] for s in argv if s.endswith(":/workspace"))
        Path(ws, "output.json").write_text(
            json.dumps({"summary": "ok", "vram_total_mb": 40960, "metrics": {"x": 1}})
        )
        return _completed(0, stdout="ok\n")

    fake.queue(_completed(0))  # image inspect → present
    # Replace the next queued behaviour with the side-effect dispatch:
    class _SideEffect:
        pass

    # Use a small wrapper: we need fake.__call__ to invoke the side effect
    # for the second call. Simplest: extend _FakeRun to allow callables.
    fake.behaviours.append(docker_run_side_effect)

    # Patch _FakeRun.__call__ to invoke callable behaviours:
    original_call = _FakeRun.__call__

    def patched_call(self, argv, **kwargs):
        self.calls.append(list(argv))
        if not self.behaviours:
            raise AssertionError(f"unexpected subprocess.run call: {argv}")
        b = self.behaviours.pop(0)
        if isinstance(b, Exception):
            raise b
        if callable(b) and not isinstance(b, subprocess.CompletedProcess):
            return b(argv, **kwargs)
        return b

    _FakeRun.__call__ = patched_call  # type: ignore[method-assign]
    try:
        runner = _runner(tmp_path, fake)
        tool = _gpu_tool(tmp_path / "tooldir")
        (tmp_path / "tooldir").mkdir()
        result = runner.run(tool, session_id="sess-success", note="hi")
    finally:
        _FakeRun.__call__ = original_call  # type: ignore[method-assign]

    assert result["summary"] == "ok"
    assert result["session_id"] == "sess-success"
    assert result["metrics"]["x"] == 1
    assert "elapsed_s" in result["metrics"]

    # First call was image inspect, second was docker run.
    assert fake.calls[0][:3] == ["docker", "image", "inspect"]
    assert fake.calls[1][:2] == ["docker", "run"]

    # input.json was written with the kwargs:
    inp = json.loads((tmp_path / "sess-success" / "input.json").read_text())
    assert inp == {"note": "hi"}


def test_run_nonzero_exit_returns_structured_error(tmp_path: Path) -> None:
    fake = _FakeRun()
    fake.queue(_completed(0))  # image inspect ok
    fake.queue(_completed(137, stderr="OOM killed\n"))  # docker run failed

    runner = _runner(tmp_path, fake)
    tool = _gpu_tool(tmp_path / "tooldir")
    (tmp_path / "tooldir").mkdir()
    result = runner.run(tool, session_id="sess-fail")

    assert result["error"] == "container_nonzero_exit"
    assert "137" in result["summary"]
    assert result["session_id"] == "sess-fail"
    assert "OOM killed" in result["details"]["stderr_tail"]


def test_run_timeout_returns_structured_error(tmp_path: Path) -> None:
    fake = _FakeRun()
    fake.queue(_completed(0))  # image inspect ok
    fake.queue(subprocess.TimeoutExpired(cmd=["docker"], timeout=60))

    runner = _runner(tmp_path, fake)
    tool = _gpu_tool(tmp_path / "tooldir")
    (tmp_path / "tooldir").mkdir()
    result = runner.run(tool, session_id="sess-timeout")

    assert result["error"] == "timeout"
    assert "60s" in result["summary"]


def test_run_missing_image_triggers_build(tmp_path: Path) -> None:
    fake = _FakeRun()
    # image inspect → missing.
    fake.queue(_completed(1, stderr="No such image"))
    # docker build → ok.
    fake.queue(_completed(0, stdout="Successfully built x"))

    # docker run → ok and writes output.json
    def docker_run_side_effect(argv, **_kw):
        ws = next(s.split(":")[0] for s in argv if s.endswith(":/workspace"))
        Path(ws, "output.json").write_text(json.dumps({"summary": "built ok", "metrics": {}}))
        return _completed(0)

    # Re-use the callable-aware __call__ from above.
    original_call = _FakeRun.__call__

    def patched_call(self, argv, **kwargs):
        self.calls.append(list(argv))
        b = self.behaviours.pop(0)
        if isinstance(b, Exception):
            raise b
        if callable(b) and not isinstance(b, subprocess.CompletedProcess):
            return b(argv, **kwargs)
        return b

    _FakeRun.__call__ = patched_call  # type: ignore[method-assign]
    fake.queue(docker_run_side_effect)

    try:
        runner = _runner(tmp_path, fake)
        tool_dir = tmp_path / "tooldir"
        tool_dir.mkdir()
        tool = _gpu_tool(tool_dir)
        result = runner.run(tool, session_id="sess-build")
    finally:
        _FakeRun.__call__ = original_call  # type: ignore[method-assign]

    assert result["summary"] == "built ok"
    assert fake.calls[0][:3] == ["docker", "image", "inspect"]
    assert fake.calls[1][:2] == ["docker", "build"]
    # Build context is now a staged tempdir (see _copy_build_context) rather
    # than the tool dir directly, so we assert the build was invoked with
    # *some* context path rather than the original tool_dir.
    assert fake.calls[1][-1].startswith("/tmp/") or fake.calls[1][-1].startswith("/var/")
    assert fake.calls[2][:2] == ["docker", "run"]


def test_run_container_zero_but_no_output(tmp_path: Path) -> None:
    fake = _FakeRun()
    fake.queue(_completed(0))  # inspect
    fake.queue(_completed(0, stdout="exited clean but wrote nothing"))  # run

    runner = _runner(tmp_path, fake)
    tool = _gpu_tool(tmp_path / "tooldir")
    (tmp_path / "tooldir").mkdir()
    result = runner.run(tool, session_id="sess-empty")

    assert result["error"] == "missing_output_json"


def test_run_refuses_plain_tool(tmp_path: Path) -> None:
    fake = _FakeRun()
    runner = _runner(tmp_path, fake)
    plain = Tool(
        name="test.plain",
        display_name="p",
        description="d",
        category="test",
        parameters={"type": "object", "properties": {}},
        function=lambda **_: {},
    )
    result = runner.run(plain)
    assert result["error"] == "bad_dispatch"


def test_run_image_build_failure(tmp_path: Path) -> None:
    fake = _FakeRun()
    fake.queue(_completed(1))  # inspect: missing
    fake.queue(_completed(1, stderr="bad Dockerfile"))  # build: fails

    runner = _runner(tmp_path, fake)
    tool_dir = tmp_path / "tooldir"
    tool_dir.mkdir()
    tool = _gpu_tool(tool_dir)
    result = runner.run(tool, session_id="sess-build-fail")
    assert result["error"] == "image_build_failed"
    assert "bad Dockerfile" in result["details"]["stderr_tail"]

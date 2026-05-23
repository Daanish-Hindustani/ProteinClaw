"""``LocalRunner`` — the only place that knows about Docker.

For every GPU tool invocation we:
  1. Mint or accept a ``session_id`` and provision the host workspace dir.
  2. Serialise kwargs to ``<workspace>/input.json``.
  3. Ensure the tool's Docker image exists (build it from the tool dir if not).
  4. ``docker run --gpus all`` with the workspace + weight caches mounted.
  5. Enforce ``tool.timeout_s`` and read ``<workspace>/output.json``.

Every failure path returns a structured envelope ``{summary, error, metrics}``
— no exception escapes ``run()`` (PLAN.md Task 1.5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from proteinclaw.tools import Tool

# Files copied from the package into every GPU tool's Docker build context.
# Each tool's Dockerfile can `COPY _gpu_metrics.py /app/` without per-tool
# duplication of the shared monitor module.
_SHARED_BUILD_FILES = ("_gpu_metrics.py",)

# Weight caches mounted into every GPU container (PRD §9.6). These directories
# are created on the host if they don't exist — Docker would happily create
# them as root-owned otherwise, which is a footgun on multi-user boxes.
WEIGHT_CACHE_MOUNTS: tuple[tuple[str, str], ...] = (
    ("~/.cache/huggingface", "/root/.cache/huggingface"),
    ("~/.cache/rfdiffusion", "/root/.cache/rfdiffusion"),
    ("~/.cache/proteinmpnn", "/root/.cache/proteinmpnn"),
    ("~/.cache/openfold", "/root/.cache/openfold"),
)

# Where per-session workspaces live on the host.
DEFAULT_WORKSPACE_ROOT = Path("~/.proteinclaw/gpu-workspace").expanduser()


@dataclass(frozen=True)
class RunPaths:
    """The on-disk layout for a single ``LocalRunner.run()`` invocation."""

    session_id: str
    workspace: Path  # host path mounted to /workspace inside container
    input_json: Path
    output_json: Path


def _docker_bin() -> Optional[str]:
    return shutil.which("docker")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def prepare_session(
    session_id: Optional[str] = None,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
) -> RunPaths:
    """Allocate / find the per-session workspace and return its paths."""
    sid = session_id or uuid.uuid4().hex
    workspace = (workspace_root / sid).resolve()
    _ensure_dir(workspace)
    return RunPaths(
        session_id=sid,
        workspace=workspace,
        input_json=workspace / "input.json",
        output_json=workspace / "output.json",
    )


def build_docker_run_argv(
    tool: Tool,
    paths: RunPaths,
    *,
    docker_bin: str = "docker",
    extra_env: Optional[dict[str, str]] = None,
) -> list[str]:
    """Construct the ``docker run`` command for a tool. Pure function (testable)."""
    argv: list[str] = [
        docker_bin,
        "run",
        "--rm",
        "--gpus",
        "all",
        # Tool runs as the host UID/GID so artifacts written into the
        # workspace aren't root-owned. ``-u`` requires the container user to
        # be able to read the entrypoint; our tool Dockerfiles must not set
        # USER to something restrictive.
        "-u",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{paths.workspace}:/workspace",
    ]
    for host, container in WEIGHT_CACHE_MOUNTS:
        host_expanded = Path(host).expanduser()
        _ensure_dir(host_expanded)
        argv += ["-v", f"{host_expanded}:{container}"]

    env = {
        "INPUT_FILE": "/workspace/input.json",
        "OUTPUT_FILE": "/workspace/output.json",
        "SESSION_ID": paths.session_id,
        "TOOL_NAME": tool.name,
    }
    if extra_env:
        env.update(extra_env)
    for key, value in env.items():
        argv += ["-e", f"{key}={value}"]

    if not tool.docker_image:
        raise ValueError(f"tool {tool.name!r} has no docker_image set")
    argv.append(tool.docker_image)
    return argv


class LocalRunner:
    """Docker-based dispatcher for GPU tools.

    Construct with ``LocalRunner()`` in production; tests inject
    ``run_subprocess`` to mock the shell out without touching real Docker.
    """

    def __init__(
        self,
        *,
        workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
        run_subprocess: Any = subprocess.run,
        docker_bin: Optional[str] = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).expanduser()
        self._run_subprocess = run_subprocess
        # Allow tests to inject a specific path; production discovers it.
        self._docker_bin = docker_bin or _docker_bin() or "docker"

    # --- public ---------------------------------------------------------------

    def run(
        self,
        tool: Tool,
        *,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not tool.requires_gpu:
            # The router enforces this routing decision; reaching here means
            # the caller used LocalRunner directly with a plain tool, which is
            # a programming error worth flagging loudly.
            return _error_envelope(
                summary=f"Error: LocalRunner refusing non-GPU tool {tool.name!r}",
                error="bad_dispatch",
            )

        if shutil.which(self._docker_bin) is None and self._run_subprocess is subprocess.run:
            return _error_envelope(
                summary=f"Error: docker binary not found ({self._docker_bin!r})",
                error="docker_missing",
            )

        paths = prepare_session(session_id, self._workspace_root)

        try:
            paths.input_json.write_text(json.dumps(kwargs), encoding="utf-8")
        except OSError as exc:
            return _error_envelope(
                summary=f"Error: could not write input.json: {exc}",
                error="workspace_io_error",
                session_id=paths.session_id,
            )

        # output.json is the container's responsibility; clear any stale file
        # from a previous run with the same session_id.
        if paths.output_json.exists():
            try:
                paths.output_json.unlink()
            except OSError:
                pass

        ensure_image_result = self._ensure_image(tool)
        if ensure_image_result is not None:
            ensure_image_result.setdefault("session_id", paths.session_id)
            return ensure_image_result

        argv = build_docker_run_argv(tool, paths, docker_bin=self._docker_bin)

        t0 = time.monotonic()
        try:
            proc = self._run_subprocess(
                argv,
                capture_output=True,
                text=True,
                timeout=tool.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _error_envelope(
                summary=(
                    f"Error: {tool.name} timed out after {tool.timeout_s}s"
                ),
                error="timeout",
                session_id=paths.session_id,
                metrics={"elapsed_s": tool.timeout_s},
                details={"stderr_tail": _tail(getattr(exc, "stderr", "") or "")},
            )
        except OSError as exc:
            return _error_envelope(
                summary=f"Error: failed to invoke docker: {exc}",
                error="docker_invoke_error",
                session_id=paths.session_id,
            )
        elapsed = time.monotonic() - t0

        if proc.returncode != 0:
            return _error_envelope(
                summary=f"Error: container exited {proc.returncode}",
                error="container_nonzero_exit",
                session_id=paths.session_id,
                metrics={"elapsed_s": round(elapsed, 3)},
                details={
                    "return_code": proc.returncode,
                    "stderr_tail": _tail(proc.stderr or ""),
                },
            )

        if not paths.output_json.exists():
            return _error_envelope(
                summary="Error: container exited 0 but did not write output.json",
                error="missing_output_json",
                session_id=paths.session_id,
                metrics={"elapsed_s": round(elapsed, 3)},
                details={"stdout_tail": _tail(proc.stdout or "")},
            )

        try:
            envelope = json.loads(paths.output_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _error_envelope(
                summary=f"Error: could not parse output.json: {exc}",
                error="bad_output_json",
                session_id=paths.session_id,
                metrics={"elapsed_s": round(elapsed, 3)},
            )

        if not isinstance(envelope, dict):
            return _error_envelope(
                summary="Error: output.json was not a JSON object",
                error="bad_output_shape",
                session_id=paths.session_id,
                metrics={"elapsed_s": round(elapsed, 3)},
            )

        envelope.setdefault("session_id", paths.session_id)
        envelope.setdefault("metrics", {})
        if isinstance(envelope["metrics"], dict):
            envelope["metrics"].setdefault("elapsed_s", round(elapsed, 3))
        return _translate_workspace_paths(envelope, paths.workspace)

    # --- internals ------------------------------------------------------------

    def _ensure_image(self, tool: Tool) -> Optional[dict[str, Any]]:
        """Build the tool's Docker image if it isn't present.

        Returns ``None`` on success or an error envelope on failure.
        """
        if not tool.docker_image:
            return _error_envelope(
                summary=f"Error: tool {tool.name!r} has no docker_image set",
                error="tool_misconfigured",
            )

        inspect = self._run_subprocess(
            [self._docker_bin, "image", "inspect", tool.docker_image],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if inspect.returncode == 0:
            return None

        if not tool.tool_dir:
            return _error_envelope(
                summary=(
                    f"Error: image {tool.docker_image!r} missing and tool {tool.name!r} "
                    f"has no tool_dir to build from"
                ),
                error="image_missing_no_build_context",
            )

        # 30-min build cap is generous for the smoke tool but reasonable for
        # real model images. Heavy images (ESMFold, AF2) can override via
        # ``execution.timeout_s`` — the build cap is max(timeout_s, 30 min).
        # Heavy model images can exceed 30 min on a cold cache; cap at 2h.
        build_timeout = max(tool.timeout_s, 7200)

        # Stage a build context that combines the tool dir with any
        # cross-tool shared files (e.g. _gpu_metrics.py). The cleanup happens
        # in `finally` so a build crash doesn't leak the tempdir.
        try:
            with tempfile.TemporaryDirectory(prefix="proteinclaw-build-") as staging:
                staging_path = Path(staging)
                _copy_build_context(Path(tool.tool_dir), staging_path)
                try:
                    proc = self._run_subprocess(
                        [
                            self._docker_bin,
                            "build",
                            "-t",
                            tool.docker_image,
                            str(staging_path),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=build_timeout,
                    )
                except (subprocess.TimeoutExpired, OSError) as exc:
                    return _error_envelope(
                        summary=f"Error: docker build timed out / failed: {exc}",
                        error="image_build_error",
                    )
        except OSError as exc:
            return _error_envelope(
                summary=f"Error: could not stage build context: {exc}",
                error="image_build_stage_error",
            )

        if proc.returncode != 0:
            return _error_envelope(
                summary=f"Error: docker build failed for {tool.docker_image!r}",
                error="image_build_failed",
                details={
                    "return_code": proc.returncode,
                    "stderr_tail": _tail(proc.stderr or ""),
                },
            )
        return None


def _translate_workspace_paths(envelope: Any, host_workspace: Path) -> Any:
    """Rewrite ``/workspace/...`` paths in the envelope to host paths.

    Containers see the session workspace at ``/workspace``; callers on the
    host need the absolute host path. Recurses into nested dicts/lists so
    tool-specific fields (``fasta_path``, ``pdb_path``, list of design
    paths, etc.) get translated regardless of where they sit in the shape.
    Non-string leaves pass through unchanged.
    """
    if isinstance(envelope, dict):
        return {k: _translate_workspace_paths(v, host_workspace) for k, v in envelope.items()}
    if isinstance(envelope, list):
        return [_translate_workspace_paths(v, host_workspace) for v in envelope]
    if isinstance(envelope, str):
        if envelope == "/workspace":
            return str(host_workspace)
        if envelope.startswith("/workspace/"):
            return str(host_workspace / envelope[len("/workspace/"):])
    return envelope


def _copy_build_context(tool_dir: Path, staging: Path) -> None:
    """Mirror ``tool_dir`` into ``staging`` and overlay shared package files.

    The staging dir is what Docker sees as its build context. Tool files
    win over shared files on name collision (a tool that needs to override
    a shared helper can do so by shipping its own copy).
    """
    # Tool files first (so tool-local overrides win).
    for src in tool_dir.iterdir():
        dst = staging / src.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    # Shared package files — only added if the tool didn't already provide one.
    tools_pkg = Path(__file__).resolve().parent.parent / "tools"
    for name in _SHARED_BUILD_FILES:
        src = tools_pkg / name
        dst = staging / name
        if dst.exists():
            continue
        if src.exists():
            shutil.copy2(src, dst)


def _tail(text: str, max_chars: int = 2000) -> str:
    if len(text) <= max_chars:
        return text
    return "...(truncated)...\n" + text[-max_chars:]


def _error_envelope(
    *,
    summary: str,
    error: str,
    session_id: Optional[str] = None,
    metrics: Optional[dict[str, Any]] = None,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "summary": summary,
        "error": error,
        "metrics": metrics or {},
    }
    if session_id is not None:
        envelope["session_id"] = session_id
    if details:
        envelope["details"] = details
    return envelope


__all__ = ["LocalRunner", "RunPaths", "WEIGHT_CACHE_MOUNTS", "build_docker_run_argv", "prepare_session"]

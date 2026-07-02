"""``ComputeRouter`` — decide where each tool runs.

The router is the single seam between the agent loop and the runtime: tools
declare ``requires_gpu`` + ``min_vram_gb``; the router consults the local
hardware once per session and either calls the tool in-process or delegates
to ``LocalRunner`` for Docker dispatch.

Local-only in v1. Cloud/SLURM hooks would slot in here without changes
elsewhere; the agent never reaches past this boundary.

Every error is returned as a structured envelope: no exception leaves
``route()``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

from proteinclaw.tools import Tool

# Smuggled-in for type hints without forcing import at module load time.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proteinclaw.runner.local import LocalRunner


@dataclass(frozen=True)
class GPUInfo:
    available: bool
    total_vram_mb: int  # max across detected GPUs (0 if none)
    reason: Optional[str] = None  # populated when available=False


def _probe_gpu() -> GPUInfo:
    """Run ``nvidia-smi`` once. Never raises."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return GPUInfo(False, 0, reason="nvidia-smi not found on PATH")
    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return GPUInfo(False, 0, reason=f"nvidia-smi failed: {exc}")
    if proc.returncode != 0:
        return GPUInfo(
            False,
            0,
            reason=f"nvidia-smi exit {proc.returncode}: {proc.stderr.strip()[:200]}",
        )
    sizes: list[int] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            sizes.append(int(line))
        except ValueError:
            return GPUInfo(False, 0, reason=f"nvidia-smi parse error on line {line!r}")
    if not sizes:
        return GPUInfo(False, 0, reason="nvidia-smi returned no GPUs")
    return GPUInfo(True, max(sizes))


class ComputeRouter:
    """Routes a tool call to the right execution backend.

    A fresh ``ComputeRouter`` probes the GPU on first GPU-tool dispatch and
    caches the result. Tests construct a new router (or pass ``gpu_info``
    explicitly) to get a fresh probe.
    """

    def __init__(
        self,
        *,
        runner: Optional["LocalRunner"] = None,
        gpu_info: Optional[GPUInfo] = None,
    ) -> None:
        self._runner = runner
        self._gpu_info_override = gpu_info
        self._gpu_info_cache: Optional[GPUInfo] = None

    def gpu_info(self) -> GPUInfo:
        if self._gpu_info_override is not None:
            return self._gpu_info_override
        if self._gpu_info_cache is None:
            self._gpu_info_cache = _probe_gpu()
        return self._gpu_info_cache

    def _get_runner(self) -> "LocalRunner":
        if self._runner is None:
            # Lazy import: routes that don't touch GPU shouldn't pay the cost
            # of importing the Docker-dispatch module.
            from proteinclaw.runner.local import LocalRunner

            self._runner = LocalRunner()
        return self._runner

    def route(self, tool: Tool, /, **kwargs: Any) -> dict[str, Any]:
        """Dispatch ``tool`` with ``kwargs``. Returns the tool result envelope."""
        if not tool.requires_gpu:
            return self._call_in_process(tool, kwargs)

        info = self.gpu_info()
        if not info.available:
            return _error_envelope(
                summary=f"Error: GPU unavailable ({info.reason})",
                error="compute_unavailable",
                details={"min_vram_gb": tool.min_vram_gb},
            )
        total_gb = info.total_vram_mb // 1024
        if total_gb < tool.min_vram_gb:
            return _error_envelope(
                summary=(
                    f"Error: GPU below floor ({total_gb} GB available, "
                    f"{tool.min_vram_gb} GB required for {tool.name})"
                ),
                error="compute_unavailable",
                details={
                    "available_vram_gb": total_gb,
                    "min_vram_gb": tool.min_vram_gb,
                },
            )

        try:
            return self._get_runner().run(tool, **kwargs)
        except Exception as exc:  # noqa: BLE001 — never let the agent crash
            return _error_envelope(
                summary=f"Error: runner crashed unexpectedly: {exc}",
                error="runner_crash",
                details={"exception_type": type(exc).__name__},
            )

    @staticmethod
    def _call_in_process(tool: Tool, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            result = tool.function(**kwargs)
        except Exception as exc:  # noqa: BLE001 — uniform envelope contract
            return _error_envelope(
                summary=f"Error: {tool.name} raised {type(exc).__name__}: {exc}",
                error="tool_exception",
                details={"exception_type": type(exc).__name__},
            )
        if not isinstance(result, dict):
            return _error_envelope(
                summary=(
                    f"Error: {tool.name} returned a non-dict result "
                    f"({type(result).__name__}). All tools must return the envelope."
                ),
                error="bad_result_shape",
            )
        return result


def _error_envelope(
    *,
    summary: str,
    error: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {"summary": summary, "error": error, "metrics": {}}
    if details:
        envelope["details"] = details
    return envelope


__all__ = ["ComputeRouter", "GPUInfo"]

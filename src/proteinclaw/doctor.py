"""``proteinclaw doctor`` — preflight checks for the local environment.

Each check is a pure function returning ``CheckResult``: easy to unit-test
without touching real ``nvidia-smi`` / ``docker`` (PLAN.md Task 1.6).

Required checks (failure → non-zero exit and blocks ``proteinclaw run``):
  - GPU present
  - GPU VRAM ≥ global floor (24 GB, the AF2-multimer requirement)
  - Docker daemon reachable
  - NVIDIA Container Toolkit functional (Docker can see the GPU)
  - Gemini API key configured

Advisory checks (failure → warn but don't block):
  - Free disk ≥ 200 GB
  - Network reachability to external science APIs
  - Weight cache directories exist
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from proteinclaw.runner.router import _probe_gpu

# Global VRAM floor: AF2-multimer's min_vram_gb (PRD §9.6). Smaller tools
# have lower floors, but if you can't run AF2 you can't run the pipeline.
GLOBAL_VRAM_FLOOR_GB = 24

# Free-disk threshold (PRD §10 — README hardware reqs say 200 GB).
DISK_FLOOR_GB = 200

DOCTOR_MARKER = Path("~/.proteinclaw/doctor_ok").expanduser()
DEFAULT_CONFIG = Path("~/.proteinclaw/config.toml").expanduser()


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str
    required: bool

    @property
    def ok(self) -> bool:
        return self.status is Status.PASS

    @property
    def blocking(self) -> bool:
        return self.required and self.status is Status.FAIL


# --- individual checks ------------------------------------------------------


def check_gpu_present() -> CheckResult:
    info = _probe_gpu()
    if info.available:
        return CheckResult(
            "gpu",
            Status.PASS,
            f"GPU available ({info.total_vram_mb} MB total VRAM on largest card)",
            required=True,
        )
    return CheckResult("gpu", Status.FAIL, info.reason or "no GPU detected", required=True)


def check_gpu_vram(floor_gb: int = GLOBAL_VRAM_FLOOR_GB) -> CheckResult:
    info = _probe_gpu()
    if not info.available:
        return CheckResult(
            "vram",
            Status.FAIL,
            "cannot check VRAM — GPU not available",
            required=True,
        )
    total_gb = info.total_vram_mb // 1024
    if total_gb >= floor_gb:
        return CheckResult(
            "vram",
            Status.PASS,
            f"{total_gb} GB ≥ {floor_gb} GB floor",
            required=True,
        )
    return CheckResult(
        "vram",
        Status.FAIL,
        f"{total_gb} GB < {floor_gb} GB floor (AF2-multimer will OOM)",
        required=True,
    )


def check_docker(run_subprocess: Callable = subprocess.run) -> CheckResult:
    binary = shutil.which("docker")
    if binary is None:
        return CheckResult("docker", Status.FAIL, "docker not on PATH", required=True)
    try:
        proc = run_subprocess(
            [binary, "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult(
            "docker", Status.FAIL, f"docker info failed: {exc}", required=True
        )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        return CheckResult(
            "docker",
            Status.FAIL,
            f"docker daemon unreachable: {tail[0]}",
            required=True,
        )
    return CheckResult("docker", Status.PASS, "docker daemon reachable", required=True)


def check_nvidia_container_toolkit(
    run_subprocess: Callable = subprocess.run,
) -> CheckResult:
    binary = shutil.which("docker")
    if binary is None:
        return CheckResult(
            "nvidia-ctk", Status.FAIL, "docker missing", required=True
        )
    # The cheapest end-to-end probe: ask Docker to list GPUs via the runtime.
    # `nvidia-ctk` itself may not be on PATH (e.g., if installed elsewhere);
    # the functional test is whether `docker run --gpus all` actually works.
    try:
        proc = run_subprocess(
            [
                binary,
                "run",
                "--rm",
                "--gpus",
                "all",
                "nvidia/cuda:12.4.1-base-ubuntu22.04",
                "nvidia-smi",
                "-L",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult(
            "nvidia-ctk",
            Status.FAIL,
            f"GPU container probe failed: {exc}",
            required=True,
        )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        return CheckResult(
            "nvidia-ctk",
            Status.FAIL,
            f"docker --gpus all not functional: {tail[0]}",
            required=True,
        )
    return CheckResult(
        "nvidia-ctk",
        Status.PASS,
        "docker --gpus all reaches the GPU",
        required=True,
    )


def check_gemini_key(
    env: Optional[dict[str, str]] = None,
    config_path: Path = DEFAULT_CONFIG,
) -> CheckResult:
    env = env if env is not None else os.environ  # type: ignore[assignment]
    if env.get("GEMINI_API_KEY"):  # type: ignore[union-attr]
        return CheckResult(
            "gemini-key", Status.PASS, "GEMINI_API_KEY present in env", required=True
        )
    if config_path.exists():
        try:
            with config_path.open("rb") as f:
                config = tomllib.load(f)
            if config.get("gemini", {}).get("api_key"):
                return CheckResult(
                    "gemini-key",
                    Status.PASS,
                    f"api_key present in {config_path}",
                    required=True,
                )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return CheckResult(
                "gemini-key",
                Status.FAIL,
                f"{config_path} unreadable: {exc}",
                required=True,
            )
    return CheckResult(
        "gemini-key",
        Status.FAIL,
        f"set GEMINI_API_KEY or write [gemini]\\napi_key=\"...\" to {config_path}",
        required=True,
    )


def check_disk(
    path: Path = Path.home(),
    floor_gb: int = DISK_FLOOR_GB,
) -> CheckResult:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return CheckResult("disk", Status.WARN, f"could not stat {path}: {exc}", required=False)
    free_gb = usage.free // (1024**3)
    if free_gb >= floor_gb:
        return CheckResult(
            "disk", Status.PASS, f"{free_gb} GB free on {path}", required=False
        )
    return CheckResult(
        "disk",
        Status.WARN,
        f"only {free_gb} GB free on {path} (< {floor_gb} GB recommended)",
        required=False,
    )


def check_network(timeout: float = 5.0) -> CheckResult:
    """Probe DNS + TCP to a science API host. Advisory only."""
    targets = [("rest.uniprot.org", 443), ("data.rcsb.org", 443)]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return CheckResult(
                    "network",
                    Status.PASS,
                    f"reached {host}:{port}",
                    required=False,
                )
        except OSError:
            continue
    return CheckResult(
        "network",
        Status.WARN,
        f"could not reach any of: {[h for h, _ in targets]}",
        required=False,
    )


_WEIGHT_CACHE_DIRS = (
    "~/.cache/huggingface",
    "~/.cache/rfdiffusion",
    "~/.cache/proteinmpnn",
    "~/.cache/openfold",
)


def check_weight_caches() -> CheckResult:
    missing = [p for p in _WEIGHT_CACHE_DIRS if not Path(p).expanduser().exists()]
    if not missing:
        return CheckResult(
            "weights", Status.PASS, "all weight cache directories present", required=False
        )
    return CheckResult(
        "weights",
        Status.WARN,
        f"missing (will be created on first use): {missing}",
        required=False,
    )


# --- aggregation ------------------------------------------------------------


_ALL_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_gpu_present,
    check_gpu_vram,
    check_docker,
    check_nvidia_container_toolkit,
    check_gemini_key,
    check_disk,
    check_network,
    check_weight_caches,
)


def run_all_checks() -> list[CheckResult]:
    """Run every check sequentially. Each check captures its own failures."""
    results: list[CheckResult] = []
    for check in _ALL_CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 — never crash doctor
            results.append(
                CheckResult(
                    check.__name__, Status.FAIL, f"check raised: {exc}", required=True
                )
            )
    return results


def render_table(results: list[CheckResult]) -> str:
    name_w = max((len(r.name) for r in results), default=4)
    lines = [
        f"{'CHECK'.ljust(name_w)}  STATUS  DETAIL",
        f"{'-' * name_w}  ------  ------",
    ]
    for r in results:
        lines.append(f"{r.name.ljust(name_w)}  {r.status.value:<6}  {r.message}")
    return "\n".join(lines)


def aggregate_exit_code(results: list[CheckResult]) -> int:
    return 1 if any(r.blocking for r in results) else 0


def write_marker_if_clean(results: list[CheckResult]) -> None:
    if aggregate_exit_code(results) != 0:
        if DOCTOR_MARKER.exists():
            try:
                DOCTOR_MARKER.unlink()
            except OSError:
                pass
        return
    DOCTOR_MARKER.parent.mkdir(parents=True, exist_ok=True)
    DOCTOR_MARKER.write_text("ok\n", encoding="utf-8")


def doctor_ok() -> bool:
    """``proteinclaw run`` gate."""
    return DOCTOR_MARKER.exists()


def run_doctor(
    *,
    self_test: bool = False,
    stream=sys.stdout,
) -> int:
    results = run_all_checks()
    print(render_table(results), file=stream)
    write_marker_if_clean(results)
    exit_code = aggregate_exit_code(results)
    if exit_code != 0:
        print("\nDoctor: FAIL — fix the above before `proteinclaw run`.", file=stream)
        return exit_code

    print("\nDoctor: PASS", file=stream)

    if self_test:
        print("\nRunning GPU tool integration suite (`pytest -m gpu`)...", file=stream)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "gpu", "tests/tools"],
            check=False,
        )
        return proc.returncode

    return 0


__all__ = [
    "CheckResult",
    "DOCTOR_MARKER",
    "GLOBAL_VRAM_FLOOR_GB",
    "Status",
    "aggregate_exit_code",
    "check_disk",
    "check_docker",
    "check_gemini_key",
    "check_gpu_present",
    "check_gpu_vram",
    "check_network",
    "check_nvidia_container_toolkit",
    "check_weight_caches",
    "doctor_ok",
    "render_table",
    "run_all_checks",
    "run_doctor",
    "write_marker_if_clean",
]

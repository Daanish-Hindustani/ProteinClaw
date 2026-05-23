"""Smoke GPU tool — shells ``nvidia-smi`` and returns memory info.

Lives inside the container; not imported on the host. Keeps deps to the
standard library only so the Dockerfile can stay slim.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any


def _query_nvidia_smi() -> tuple[int, int]:
    """Return ``(used_mb, total_mb)`` for GPU 0. Raises on failure."""
    nvidia_smi = shutil.which("nvidia-smi") or "/usr/bin/nvidia-smi"
    proc = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
            "-i",
            "0",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    line = proc.stdout.strip().splitlines()[0]
    used_str, total_str = (p.strip() for p in line.split(","))
    return int(used_str), int(total_str)


def run(*, note: str = "") -> dict[str, Any]:
    """Smoke test: confirm GPU is visible inside the container."""
    t0 = time.monotonic()
    used_mb, total_mb = _query_nvidia_smi()
    elapsed = time.monotonic() - t0

    summary = f"smoke ok — GPU 0 reports {used_mb}/{total_mb} MB used/total"
    if note:
        summary = f"{summary} (note: {note})"

    return {
        "summary": summary,
        "vram_used_mb": used_mb,
        "vram_total_mb": total_mb,
        "note": note,
        "metrics": {
            "vram_before_mb": used_mb,
            "vram_peak_mb": used_mb,
            "elapsed_s": round(elapsed, 3),
        },
        "session_id": os.environ.get("SESSION_ID", ""),
    }

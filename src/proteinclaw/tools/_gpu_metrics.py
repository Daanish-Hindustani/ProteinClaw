"""Shared VRAM monitor for in-container use (PLAN.md Task 3.1).

This module is **shipped into every GPU tool's container** by the
``LocalRunner`` build-context staging — each ``Dockerfile`` just does
``COPY _gpu_metrics.py /app/`` and the module is importable next to
``implementation.py``.

Standard-library only on purpose: every tool's container should be able to
import this without adding to its dep tree.

Usage::

    from _gpu_metrics import VramMonitor

    with VramMonitor() as m:
        ...real work...
    metrics = {"vram_before_mb": m.before, "vram_peak_mb": m.peak}
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from typing import Optional


def vram_mb(device: int = 0) -> int:
    """Return current GPU memory used (MB) on the given device, 0 on failure."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return 0
    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                "-i",
                str(device),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return 0
        line = proc.stdout.strip().splitlines()[0]
        return int(line)
    except (OSError, ValueError, IndexError):
        return 0


class VramMonitor:
    """Context manager that samples VRAM use in a background thread.

    Records the initial reading (``before``) at entry, then samples every
    ``interval`` seconds and keeps the maximum (``peak``). Exit joins the
    thread, so timing is deterministic for tests.
    """

    def __init__(self, interval: float = 0.5, device: int = 0) -> None:
        self.interval = interval
        self.device = device
        self.before: int = 0
        self.peak: int = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "VramMonitor":
        self.before = vram_mb(self.device)
        self.peak = self.before
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                current = vram_mb(self.device)
                if current > self.peak:
                    self.peak = current
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        # Final sample after the inner block returned — sometimes the peak
        # only registers right at the end.
        final = vram_mb(self.device)
        if final > self.peak:
            self.peak = final
        return False


def elapsed_s(t0: float) -> float:
    return round(time.monotonic() - t0, 3)


__all__ = ["VramMonitor", "elapsed_s", "vram_mb"]

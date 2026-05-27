"""Task 1.1 — package import + console-script smoke."""

from __future__ import annotations

import subprocess
import sys


def test_package_imports() -> None:
    import proteinclaw  # noqa: F401

    assert proteinclaw.__version__


def test_cli_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "proteinclaw.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "proteinclaw" in proc.stdout.lower()


def test_cli_version_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "proteinclaw.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "proteinclaw" in proc.stdout

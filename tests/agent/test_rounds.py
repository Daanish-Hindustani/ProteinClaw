"""--rounds plumbing: addendum, CLI flag, max_turns scaling."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from proteinclaw.agent.core import _rounds_addendum, run_campaign


def test_rounds_one_addendum_says_one() -> None:
    txt = _rounds_addendum(1)
    assert "1 round" in txt
    assert "not call RFD3 more than once" in txt


def test_rounds_three_addendum_describes_refinement() -> None:
    txt = _rounds_addendum(3)
    assert "Budget ceiling" in txt
    assert "3 rounds" in txt
    assert "RFD3 again" in txt
    assert "sampling_temp" in txt
    assert "Never repeat an identical hypothesis" in txt


def test_rounds_no_cap_addendum_lifts_ceiling() -> None:
    txt = _rounds_addendum(12, capped=False)
    assert "No hard round cap" in txt
    assert "quality gate" in txt


def test_rounds_zero_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rounds must be"):
        run_campaign(
            prompt="x",
            output_dir=tmp_path,
            rounds=0,
        )


def test_cli_rounds_flag_in_dry_run(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "proteinclaw.cli",
            "run",
            "design x",
            "--dry-run",
            "--skip-doctor",
            "--rounds",
            "3",
            "--max-turns",
            "40",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "rounds=3" in proc.stdout
    assert "max_turns_per_round=40" in proc.stdout
    assert "research_fanout: True" in proc.stdout
    assert "round_cap: 3" in proc.stdout


def test_cli_no_cap_no_fanout_in_dry_run(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable, "-m", "proteinclaw.cli", "run", "design x",
            "--dry-run", "--skip-doctor", "--no-cap", "--no-research-fanout",
            "--output-dir", str(tmp_path),
        ],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "round_cap: none (--no-cap)" in proc.stdout
    assert "research_fanout: False" in proc.stdout


def test_cli_rejects_rounds_out_of_range(tmp_path: Path) -> None:
    """typer enforces min/max on the flag."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "proteinclaw.cli",
            "run",
            "x",
            "--dry-run",
            "--skip-doctor",
            "--rounds",
            "99",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "rounds" in out.lower() or "99" in out

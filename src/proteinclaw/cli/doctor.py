"""`proteinclaw doctor` — system probe.

Reports whether the box is ready to run a real end-to-end query and
where the gaps are. Each `Check` is a small dataclass; `run_doctor()`
returns the full list so callers can format it (the CLI prints a
table; tests just inspect the values).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from proteinclaw.cli.config import config_exists, load_config


class CheckStatus(StrEnum):
    """Status emoji + sort order for a single check."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class Check:
    """One probe result.

    Attributes:
        name: Short label (e.g. ``"NVIDIA GPU"``).
        status: ``ok | warn | fail | skip``.
        detail: Free-form one-line detail surfaced to the user.
        fix_hint: When non-empty, points the user at how to fix.
    """

    name: str
    status: CheckStatus
    detail: str = ""
    fix_hint: str = ""


@dataclass
class DoctorReport:
    """All checks plus an overall ready/not-ready verdict."""

    checks: list[Check] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """True iff any check is FAIL — blocks `run`."""
        return any(c.status is CheckStatus.FAIL for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        """True iff any check is WARN — non-blocking but worth noting."""
        return any(c.status is CheckStatus.WARN for c in self.checks)


def run_doctor() -> DoctorReport:
    """Run every system probe and return the aggregated report."""
    report = DoctorReport()
    report.checks.append(_check_os())
    report.checks.append(_check_gpu())
    report.checks.append(_check_python())
    report.checks.append(_check_uv())
    report.checks.append(_check_config())
    report.checks.extend(_check_install_paths())
    report.checks.append(_check_disk())
    return report


def _check_os() -> Check:
    """OS probe. macOS / Windows are non-blocking unless install is requested."""
    system = platform.system()
    if system == "Linux":
        return Check("OS", CheckStatus.OK, f"{platform.platform()}")
    if system == "Darwin":
        return Check(
            "OS",
            CheckStatus.WARN,
            "macOS detected — local GPU tools (RFdiffusion, ProteinMPNN) won't run here.",
            fix_hint="Run on a Linux GPU box (Lambda Labs etc.) for the full pipeline.",
        )
    return Check(
        "OS",
        CheckStatus.FAIL,
        f"unsupported platform: {system}",
        fix_hint="ProteinClaw targets Linux + (optionally) macOS for development.",
    )


def _check_gpu() -> Check:
    """`nvidia-smi` presence + GPU model + driver."""
    if not shutil.which("nvidia-smi"):
        return Check(
            "NVIDIA GPU",
            CheckStatus.FAIL,
            "nvidia-smi not on PATH",
            fix_hint="Install the NVIDIA driver before running setup with --install-tools.",
        )
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return Check("NVIDIA GPU", CheckStatus.FAIL, f"nvidia-smi failed: {e}")
    if out.returncode != 0:
        return Check(
            "NVIDIA GPU",
            CheckStatus.FAIL,
            f"nvidia-smi exit {out.returncode}: {out.stderr.strip()[:200]}",
        )
    detail = out.stdout.strip().splitlines()[0] if out.stdout.strip() else "unknown"
    return Check("NVIDIA GPU", CheckStatus.OK, detail)


def _check_python() -> Check:
    """Host Python version (the one running this CLI)."""
    v = platform.python_version_tuple()
    if int(v[0]) >= 3 and int(v[1]) >= 11:
        return Check("Python", CheckStatus.OK, platform.python_version())
    return Check(
        "Python",
        CheckStatus.WARN,
        f"detected {platform.python_version()}; expected 3.11+",
    )


def _check_uv() -> Check:
    """`uv` presence on PATH."""
    if not shutil.which("uv"):
        return Check(
            "uv",
            CheckStatus.WARN,
            "not on PATH (only matters if you reinstall ProteinClaw deps)",
        )
    return Check("uv", CheckStatus.OK, "on PATH")


def _check_config() -> Check:
    """ProteinClaw config presence + parseability."""
    if not config_exists():
        return Check(
            "ProteinClaw config",
            CheckStatus.FAIL,
            "no config found",
            fix_hint="Run `proteinclaw setup`.",
        )
    try:
        cfg = load_config()
    except Exception as e:
        return Check(
            "ProteinClaw config",
            CheckStatus.FAIL,
            f"failed to load: {e}",
            fix_hint="Re-run `proteinclaw setup`.",
        )
    return Check(
        "ProteinClaw config",
        CheckStatus.OK,
        f"provider={cfg.ai_provider} model={cfg.ai_model} tools_installed={cfg.tools_installed}",
    )


def _check_install_paths() -> list[Check]:
    """Optional install-path probes (skip when no config or tools_installed=False)."""
    if not config_exists():
        return [Check("Tool installs", CheckStatus.SKIP, "no config yet")]
    try:
        cfg = load_config()
    except Exception:
        return [Check("Tool installs", CheckStatus.SKIP, "config invalid")]
    if not cfg.tools_installed or not cfg.tools_install_root:
        return [Check("Tool installs", CheckStatus.SKIP, "user opted out of local install")]
    out: list[Check] = []
    root = Path(cfg.tools_install_root)
    for sub, var in [
        ("RFdiffusion", "RFDIFFUSION_PATH"),
        ("ProteinMPNN", "PROTEINMPNN_PATH"),
    ]:
        p = root / sub
        if p.is_dir():
            out.append(Check(sub, CheckStatus.OK, f"installed at {p}"))
        else:
            out.append(
                Check(
                    sub,
                    CheckStatus.FAIL,
                    f"missing at {p}",
                    fix_hint=f"Re-run `proteinclaw setup` or set {var} manually.",
                )
            )
    return out


def _check_disk() -> Check:
    """Cheap free-disk probe (50 GB minimum recommended for full install)."""
    usage = shutil.disk_usage(Path.home())
    free_gb = usage.free // (1024**3)
    if free_gb < 20:
        return Check(
            "Free disk (home)",
            CheckStatus.FAIL,
            f"{free_gb} GB free — need ≥ 20 GB",
        )
    if free_gb < 50:
        return Check(
            "Free disk (home)",
            CheckStatus.WARN,
            f"{free_gb} GB free — recommended ≥ 50 GB for full install",
        )
    return Check("Free disk (home)", CheckStatus.OK, f"{free_gb} GB free")

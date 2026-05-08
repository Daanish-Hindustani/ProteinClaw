"""Tests for cli/doctor.py — system probes."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.cli import config as config_mod
from proteinclaw.cli import doctor


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dir = tmp_path / ".proteinclaw"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", fake_dir / "config.json")


def test_doctor_runs_without_throwing() -> None:
    report = doctor.run_doctor()
    assert report.checks  # at least one check
    names = {c.name for c in report.checks}
    assert "OS" in names
    assert "NVIDIA GPU" in names
    assert "ProteinClaw config" in names
    assert "Free disk (home)" in names


def test_config_check_fails_when_no_config() -> None:
    report = doctor.run_doctor()
    cfg_check = next(c for c in report.checks if c.name == "ProteinClaw config")
    assert cfg_check.status is doctor.CheckStatus.FAIL
    assert "setup" in cfg_check.fix_hint.lower()


def test_config_check_ok_after_setup(tmp_path: Path) -> None:
    config_mod.save_config(config_mod.Config(ai_api_key="sk-test"))
    report = doctor.run_doctor()
    cfg_check = next(c for c in report.checks if c.name == "ProteinClaw config")
    assert cfg_check.status is doctor.CheckStatus.OK


def test_install_paths_skipped_when_user_opted_out(tmp_path: Path) -> None:
    config_mod.save_config(config_mod.Config(ai_api_key="sk-test", tools_installed=False))
    report = doctor.run_doctor()
    install_checks = [c for c in report.checks if c.name == "Tool installs"]
    assert any(c.status is doctor.CheckStatus.SKIP for c in install_checks)


def test_install_paths_fail_when_install_root_missing(tmp_path: Path) -> None:
    config_mod.save_config(
        config_mod.Config(
            ai_api_key="sk-test",
            tools_installed=True,
            tools_install_root=str(tmp_path / "nope"),
        )
    )
    report = doctor.run_doctor()
    failed = [c for c in report.checks if c.status is doctor.CheckStatus.FAIL]
    assert any(c.name in {"RFdiffusion", "ProteinMPNN"} for c in failed)


def test_install_paths_ok_when_dirs_exist(tmp_path: Path) -> None:
    install_root = tmp_path / "tools"
    (install_root / "RFdiffusion").mkdir(parents=True)
    (install_root / "ProteinMPNN").mkdir(parents=True)
    config_mod.save_config(
        config_mod.Config(
            ai_api_key="sk-test",
            tools_installed=True,
            tools_install_root=str(install_root),
        )
    )
    report = doctor.run_doctor()
    rfd = next(c for c in report.checks if c.name == "RFdiffusion")
    mpnn = next(c for c in report.checks if c.name == "ProteinMPNN")
    assert rfd.status is doctor.CheckStatus.OK
    assert mpnn.status is doctor.CheckStatus.OK


def test_has_failures_property() -> None:
    report = doctor.DoctorReport(
        checks=[
            doctor.Check("a", doctor.CheckStatus.OK),
            doctor.Check("b", doctor.CheckStatus.FAIL),
        ]
    )
    assert report.has_failures is True
    assert report.has_warnings is False

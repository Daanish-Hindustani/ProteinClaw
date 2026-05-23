"""Task 1.6 — doctor checks (unit-tested with mocks; no real nvidia-smi/docker)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from proteinclaw import doctor
from proteinclaw.doctor import (
    CheckResult,
    Status,
    aggregate_exit_code,
    check_disk,
    check_docker,
    check_anthropic_key,
    check_gpu_present,
    check_gpu_vram,
    check_network,
    check_nvidia_container_toolkit,
    check_weight_caches,
    render_table,
    write_marker_if_clean,
)


def _completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


# --- GPU checks (patch _probe_gpu) ------------------------------------------


def test_check_gpu_present_pass_real(monkeypatch) -> None:
    from proteinclaw.runner.router import GPUInfo

    monkeypatch.setattr(doctor, "_probe_gpu", lambda: GPUInfo(True, 40960))
    r = check_gpu_present()
    assert r.ok and r.required and "40960" in r.message


def test_check_gpu_present_fail(monkeypatch) -> None:
    from proteinclaw.runner.router import GPUInfo

    monkeypatch.setattr(doctor, "_probe_gpu", lambda: GPUInfo(False, 0, reason="missing"))
    r = check_gpu_present()
    assert not r.ok and r.required and "missing" in r.message


def test_check_gpu_vram_above_floor(monkeypatch) -> None:
    from proteinclaw.runner.router import GPUInfo

    monkeypatch.setattr(doctor, "_probe_gpu", lambda: GPUInfo(True, 40960))
    r = check_gpu_vram(floor_gb=24)
    assert r.ok


def test_check_gpu_vram_below_floor(monkeypatch) -> None:
    from proteinclaw.runner.router import GPUInfo

    monkeypatch.setattr(doctor, "_probe_gpu", lambda: GPUInfo(True, 8 * 1024))
    r = check_gpu_vram(floor_gb=24)
    assert not r.ok and "OOM" in r.message


# --- Docker checks ----------------------------------------------------------


def test_check_docker_missing_binary(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    r = check_docker()
    assert not r.ok and "PATH" in r.message


def test_check_docker_daemon_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/docker")
    r = check_docker(run_subprocess=lambda *a, **k: _completed(1, stderr="cannot connect\n"))
    assert not r.ok and "cannot connect" in r.message


def test_check_docker_ok(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/docker")
    r = check_docker(run_subprocess=lambda *a, **k: _completed(0, stdout="info\n"))
    assert r.ok


def test_check_nvidia_ctk_missing_docker(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    r = check_nvidia_container_toolkit()
    assert not r.ok


def test_check_nvidia_ctk_failure(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/docker")
    r = check_nvidia_container_toolkit(
        run_subprocess=lambda *a, **k: _completed(125, stderr="nvidia-container-cli init failed\n")
    )
    assert not r.ok and "nvidia-container-cli" in r.message


def test_check_nvidia_ctk_ok(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/docker")
    r = check_nvidia_container_toolkit(
        run_subprocess=lambda *a, **k: _completed(0, stdout="GPU 0: A100\n")
    )
    assert r.ok


# --- Anthropic key ----------------------------------------------------------


def test_check_anthropic_key_from_env(tmp_path) -> None:
    r = check_anthropic_key(
        env={"ANTHROPIC_API_KEY": "abc"}, config_path=tmp_path / "missing.toml"
    )
    assert r.ok and "env" in r.message


def test_check_anthropic_key_from_config(tmp_path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[anthropic]\napi_key = "abc"\n')
    r = check_anthropic_key(env={}, config_path=cfg)
    assert r.ok


def test_check_anthropic_key_missing(tmp_path) -> None:
    r = check_anthropic_key(env={}, config_path=tmp_path / "missing.toml")
    assert not r.ok


# --- Advisory checks --------------------------------------------------------


def test_check_disk_pass(tmp_path) -> None:
    r = check_disk(path=tmp_path, floor_gb=0)
    assert r.ok and not r.required


def test_check_disk_warn(tmp_path) -> None:
    # impossibly high floor → WARN, not FAIL
    r = check_disk(path=tmp_path, floor_gb=10**9)
    assert r.status is Status.WARN and not r.required


def test_check_weight_caches_warns_when_missing(monkeypatch, tmp_path) -> None:
    # Point HOME at an empty dir so none of the cache dirs exist.
    monkeypatch.setenv("HOME", str(tmp_path))
    # Re-import constants to re-evaluate ~ expansion is not needed here —
    # the function expands lazily.
    r = check_weight_caches()
    assert r.status is Status.WARN


# --- Aggregation ------------------------------------------------------------


def test_aggregate_exit_code_blocks_on_required_fail() -> None:
    results = [
        CheckResult("a", Status.PASS, "ok", required=True),
        CheckResult("b", Status.WARN, "advisory", required=False),
        CheckResult("c", Status.FAIL, "required broken", required=True),
    ]
    assert aggregate_exit_code(results) == 1


def test_aggregate_exit_code_ignores_advisory_fail() -> None:
    results = [
        CheckResult("a", Status.PASS, "ok", required=True),
        CheckResult("b", Status.FAIL, "advisory broke", required=False),
    ]
    assert aggregate_exit_code(results) == 0


def test_render_table_lists_all() -> None:
    out = render_table(
        [
            CheckResult("alpha", Status.PASS, "ok", required=True),
            CheckResult("beta", Status.FAIL, "nope", required=True),
        ]
    )
    assert "alpha" in out and "PASS" in out and "beta" in out and "FAIL" in out


def test_write_marker_creates_and_clears(monkeypatch, tmp_path) -> None:
    marker = tmp_path / "doctor_ok"
    monkeypatch.setattr(doctor, "DOCTOR_MARKER", marker)
    # All pass → marker written.
    write_marker_if_clean([CheckResult("a", Status.PASS, "ok", required=True)])
    assert marker.exists()
    # Required fail → marker removed.
    write_marker_if_clean([CheckResult("a", Status.FAIL, "no", required=True)])
    assert not marker.exists()

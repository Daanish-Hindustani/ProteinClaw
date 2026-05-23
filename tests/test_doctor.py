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
    check_claude_auth,
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


# --- Claude auth (subscription OAuth vs API key) ----------------------------


def _make_oauth(tmp_path) -> "Path":
    p = tmp_path / "creds.json"
    p.write_text('{"claudeAiOauth": {"accessToken": "sk-ant-oat01-test"}}')
    return p


def test_oauth_only_is_subscription_path(tmp_path) -> None:
    """Recommended state: claude login + no env key → subscription billing."""
    r = check_claude_auth(env={}, cred_path=_make_oauth(tmp_path))
    assert r.status is Status.PASS
    assert "subscription path active" in r.message.lower()


def test_oauth_plus_api_key_warns(tmp_path) -> None:
    """Trap: API key silently preempts OAuth and bills to API, not subscription."""
    r = check_claude_auth(
        env={"ANTHROPIC_API_KEY": "sk-ant-key-test"},
        cred_path=_make_oauth(tmp_path),
    )
    assert r.status is Status.WARN
    assert "takes precedence" in r.message.lower()


def test_api_key_only_is_api_path(tmp_path) -> None:
    r = check_claude_auth(
        env={"ANTHROPIC_API_KEY": "sk-ant-key-test"},
        cred_path=tmp_path / "no_such_file.json",
    )
    assert r.status is Status.PASS
    assert "pay-as-you-go" in r.message.lower()


def test_no_auth_fails(tmp_path) -> None:
    r = check_claude_auth(env={}, cred_path=tmp_path / "no_such_file.json")
    assert r.status is Status.FAIL
    assert "claude login" in r.message.lower()


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

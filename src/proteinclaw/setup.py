"""``proteinclaw setup`` — interactive environment walk-through."""

from __future__ import annotations

import os
from dataclasses import dataclass

import typer

from proteinclaw.doctor import (
    check_docker,
    check_gpu_present,
    check_hermes_auth,
    check_nvidia_container_toolkit,
    run_doctor,
)

HERMES_AUTH_HINT = (
    "Configure Hermes/provider credentials before running campaigns. Common options:\n"
    "  export OPENROUTER_API_KEY=...\n"
    "  export ANTHROPIC_API_KEY=...\n"
    "  export OPENAI_API_KEY=...\n"
    "or create ~/.hermes/config.toml if your Hermes installation uses that file."
)

DOCKER_HINT = (
    "Install Docker Engine: https://docs.docker.com/engine/install/\n"
    "  Then grant your user access (Linux):\n"
    "    sudo usermod -aG docker $USER && newgrp docker"
)

NVIDIA_CTK_HINT = (
    "Install the NVIDIA Container Toolkit:\n"
    "  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html\n"
    "Then register the runtime with Docker:\n"
    "  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
)


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    message: str


def _step(title: str) -> None:
    typer.echo("")
    typer.secho(f"── {title} ──", fg=typer.colors.CYAN, bold=True)


def _ok(msg: str) -> None:
    typer.secho(f"  ✓ {msg}", fg=typer.colors.GREEN)


def _warn(msg: str) -> None:
    typer.secho(f"  ! {msg}", fg=typer.colors.YELLOW)


def _fail(msg: str) -> None:
    typer.secho(f"  ✗ {msg}", fg=typer.colors.RED)


def step_hermes_auth(*, auto: bool, env: dict[str, str] | None = None) -> StepResult:
    _step("1/3  Hermes/provider authentication")
    res = check_hermes_auth(env=env if env is not None else dict(os.environ))
    if res.ok:
        _ok(res.message)
        return StepResult("hermes-auth", True, res.message)
    _fail(res.message)
    typer.echo("  " + HERMES_AUTH_HINT.replace("\n", "\n  "))
    return StepResult("hermes-auth", False, res.message)


def step_docker(*, auto: bool) -> StepResult:
    _step("2/3  Docker daemon")
    res = check_docker()
    if res.ok:
        _ok(res.message)
        return StepResult("docker", True, res.message)
    _fail(res.message)
    typer.echo("  " + DOCKER_HINT.replace("\n", "\n  "))
    return StepResult("docker", False, res.message)


def step_nvidia(*, auto: bool) -> StepResult:
    _step("3/3  NVIDIA GPU + Container Toolkit")
    gpu = check_gpu_present()
    if not gpu.ok:
        _fail(gpu.message)
        _warn("proteinclaw requires an NVIDIA GPU (>=24 GB VRAM for AF2-multimer).")
        return StepResult("nvidia", False, gpu.message)
    _ok(gpu.message)

    nv = check_nvidia_container_toolkit()
    if nv.ok:
        _ok(nv.message)
        return StepResult("nvidia", True, nv.message)
    _fail(nv.message)
    typer.echo("  " + NVIDIA_CTK_HINT.replace("\n", "\n  "))
    return StepResult("nvidia", False, nv.message)


def run_setup(*, auto: bool = False, skip_doctor: bool = False) -> int:
    """Walk all steps. Returns 0 on full success, non-zero on any failure."""
    typer.echo("proteinclaw setup — interactive environment walk-through")
    typer.echo(
        "Checks Hermes/provider auth and the local tool stack "
        "(Docker, NVIDIA Container Toolkit, GPU).\n"
        "Nothing is installed without your confirmation."
    )

    results = [
        step_hermes_auth(auto=auto),
        step_docker(auto=auto),
        step_nvidia(auto=auto),
    ]

    typer.echo("")
    typer.secho("── summary ──", fg=typer.colors.CYAN, bold=True)
    for r in results:
        mark = "✓" if r.ok else "✗"
        color = typer.colors.GREEN if r.ok else typer.colors.RED
        typer.secho(f"  {mark} {r.name:<14} {r.message}", fg=color)

    if not all(r.ok for r in results):
        typer.echo("")
        _warn("setup incomplete — address the items above and re-run `proteinclaw setup`")
        return 1

    if skip_doctor:
        typer.echo("")
        _ok("all steps passed (doctor skipped — run `proteinclaw doctor` before `run`)")
        return 0

    _step("preflight  `proteinclaw doctor`")
    return run_doctor(self_test=False)


__all__ = [
    "StepResult",
    "run_setup",
    "step_docker",
    "step_hermes_auth",
    "step_nvidia",
]

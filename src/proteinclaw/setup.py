"""``proteinclaw setup`` — interactive environment walk-through.

Guides a fresh user through the four things that must be true before
``proteinclaw run`` will work:

  1. Claude Code CLI installed (``claude`` on PATH).
  2. ``claude login`` has been run — OAuth credentials exist and
     ``ANTHROPIC_API_KEY`` is *not* set (subscription billing path).
  3. Docker daemon reachable.
  4. NVIDIA Container Toolkit functional (``docker run --gpus all``).

Nothing is installed without explicit confirmation. After all four steps
pass, ``proteinclaw doctor`` is invoked to write the ``doctor_ok`` marker
that gates ``proteinclaw run``.

This module is intentionally pure-ish — IO is delegated to small helpers
that tests can substitute via dependency injection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

import typer

from proteinclaw.doctor import (
    DEFAULT_CLAUDE_CRED_PATH,
    check_docker,
    check_gpu_present,
    check_nvidia_container_toolkit,
    run_doctor,
)

CLAUDE_NPM_PACKAGE = "@anthropic-ai/claude-code"

NODE_HINT = (
    "Node.js 20+ is required to install Claude Code via npm.\n"
    "  macOS:   brew install node\n"
    "  Ubuntu:  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - "
    "&& sudo apt-get install -y nodejs"
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


# --- IO helpers (substitutable for tests) -----------------------------------


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list[str]) -> int:
    """Run a command, streaming output to the user's terminal."""
    typer.echo(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def _step(title: str) -> None:
    typer.echo("")
    typer.secho(f"── {title} ──", fg=typer.colors.CYAN, bold=True)


def _ok(msg: str) -> None:
    typer.secho(f"  ✓ {msg}", fg=typer.colors.GREEN)


def _warn(msg: str) -> None:
    typer.secho(f"  ! {msg}", fg=typer.colors.YELLOW)


def _fail(msg: str) -> None:
    typer.secho(f"  ✗ {msg}", fg=typer.colors.RED)


def _confirm(prompt: str, *, auto: bool, default: bool = True) -> bool:
    if auto:
        typer.echo(f"  {prompt} [auto-yes]")
        return True
    return typer.confirm(f"  {prompt}", default=default)


# --- individual steps -------------------------------------------------------


def step_claude_code(
    *,
    auto: bool,
    which: Callable[[str], bool] = _which,
    runner: Callable[[list[str]], int] = _run,
) -> StepResult:
    _step("1/4  Claude Code CLI")
    if which("claude"):
        _ok("`claude` is on PATH")
        return StepResult("claude-code", True, "already installed")

    _fail("`claude` not found on PATH")
    if not which("npm"):
        _warn(NODE_HINT)
        return StepResult("claude-code", False, "npm missing")

    typer.echo(f"  Install with: npm install -g {CLAUDE_NPM_PACKAGE}")
    if not _confirm("Install Claude Code now?", auto=auto):
        return StepResult("claude-code", False, "declined install")

    rc = runner(["npm", "install", "-g", CLAUDE_NPM_PACKAGE])
    if rc != 0:
        _fail("npm install failed — install manually and re-run `proteinclaw setup`")
        return StepResult("claude-code", False, f"npm exit {rc}")

    _ok("Claude Code installed")
    return StepResult("claude-code", True, "installed")


def step_claude_login(
    *,
    auto: bool,
    which: Callable[[str], bool] = _which,
    runner: Callable[[list[str]], int] = _run,
    env: dict[str, str] | None = None,
    cred_path=DEFAULT_CLAUDE_CRED_PATH,
) -> StepResult:
    _step("2/4  Claude subscription login (OAuth)")
    env = env if env is not None else dict(os.environ)

    if env.get("ANTHROPIC_API_KEY"):
        _warn(
            "ANTHROPIC_API_KEY is set. It silently overrides OAuth and bills "
            "pay-as-you-go API credits instead of your Pro/Max subscription.\n"
            "    Unset it to use subscription billing:  unset ANTHROPIC_API_KEY"
        )

    if cred_path.exists():
        _ok(f"OAuth credentials present at {cred_path}")
        return StepResult("claude-login", True, "credentials exist")

    _fail("no OAuth credentials yet — `claude login` has not been run")
    typer.echo(
        "  `claude login` opens a browser to authenticate against your "
        "Pro/Max subscription.\n"
        "  After first login, claim your Agent SDK credit in plan settings:\n"
        "    https://support.claude.com/en/articles/15036540"
    )

    if not which("claude"):
        _fail("`claude` is not on PATH — complete step 1 first")
        return StepResult("claude-login", False, "claude CLI missing")

    if not _confirm("Run `claude login` now?", auto=auto):
        return StepResult("claude-login", False, "declined")

    rc = runner(["claude", "login"])
    if rc != 0 or not cred_path.exists():
        _fail("login did not complete — re-run `claude login` manually")
        return StepResult("claude-login", False, f"login exit {rc}")

    _ok("logged in")
    return StepResult("claude-login", True, "logged in")


def step_docker(*, auto: bool) -> StepResult:
    _step("3/4  Docker daemon")
    res = check_docker()
    if res.ok:
        _ok(res.message)
        return StepResult("docker", True, res.message)

    _fail(res.message)
    typer.echo("  " + DOCKER_HINT.replace("\n", "\n  "))
    return StepResult("docker", False, res.message)


def step_nvidia(*, auto: bool) -> StepResult:
    _step("4/4  NVIDIA GPU + Container Toolkit")
    gpu = check_gpu_present()
    if not gpu.ok:
        _fail(gpu.message)
        _warn("proteinclaw requires an NVIDIA GPU (≥24 GB VRAM for AF2-multimer).")
        return StepResult("nvidia", False, gpu.message)
    _ok(gpu.message)

    nv = check_nvidia_container_toolkit()
    if nv.ok:
        _ok(nv.message)
        return StepResult("nvidia", True, nv.message)

    _fail(nv.message)
    typer.echo("  " + NVIDIA_CTK_HINT.replace("\n", "\n  "))
    return StepResult("nvidia", False, nv.message)


# --- orchestration ----------------------------------------------------------


def run_setup(*, auto: bool = False, skip_doctor: bool = False) -> int:
    """Walk all steps. Returns 0 on full success, non-zero on any failure."""
    typer.echo("proteinclaw setup — interactive environment walk-through")
    typer.echo(
        "Checks Claude subscription auth and the local tool stack "
        "(Docker, NVIDIA Container Toolkit, GPU).\n"
        "Nothing is installed without your confirmation."
    )

    results: list[StepResult] = []
    code = step_claude_code(auto=auto)
    results.append(code)
    # Login only meaningful if claude CLI is available.
    if code.ok:
        results.append(step_claude_login(auto=auto))
    else:
        _warn("skipping `claude login` step until Claude Code is installed")
    results.append(step_docker(auto=auto))
    results.append(step_nvidia(auto=auto))

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
    "step_claude_code",
    "step_claude_login",
    "step_docker",
    "step_nvidia",
]

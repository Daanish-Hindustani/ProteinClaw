"""`proteinclaw setup` — interactive first-run wizard.

Flow:

1. Confirm the AI provider.
2. Prompt for a provider API key (or accept one in the env).
3. Ask whether to install local tools.
   - If yes: gate on Linux + nvidia-smi + ≥ 50 GB free disk; if any
     check fails we exit. The user gets a clear message about needing
     a Linux GPU box; we don't proceed in degraded mode.
   - If no: write a config that points at REST/mock backends only.
4. Run the install script (subprocess) when the user opted in.
5. Persist the config.

Tests inject the input/output streams via the `prompts` and `streams`
parameters so we can run the wizard headlessly.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from proteinclaw.cli import _console as c
from proteinclaw.cli.config import (
    Config,
    save_config,
)
from proteinclaw.cli.doctor import CheckStatus, run_doctor

DEFAULT_INSTALL_PREFIX = Path.home() / "proteinclaw-tools"
SETUP_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "lambda_labs_setup.sh"

PromptFn = Callable[[str], str]
SecretPromptFn = Callable[[str], str]


@dataclass
class WizardResult:
    """Outcome of a wizard run."""

    config: Config
    install_ran: bool
    install_returncode: int | None


def run_wizard(
    *,
    prompt: PromptFn = input,
    secret_prompt: SecretPromptFn = getpass.getpass,
    runner: Callable[[list[str]], int] | None = None,
    out: IO[str] | None = None,
) -> WizardResult:
    """Run the interactive setup. Returns the persisted config + install status.

    Args:
        prompt: Read a normal line from the user.
        secret_prompt: Read a secret (no echo). Defaults to `getpass`.
        runner: Function that runs the install script and returns its
            exit code. Defaults to `_default_runner`. Tests can stub it.
        out: Stream for streamed output. Defaults to stdout.
    """
    del out  # currently unused; reserved for tests that capture output
    runner = runner or _default_runner

    c.header("ProteinClaw setup")
    c.info("This wizard records your AI provider and (optionally) installs the GPU tools.")

    # 1. Provider.
    provider = _prompt_provider(prompt)

    # 2. API key.
    api_key = _prompt_for_provider_api_key(prompt, secret_prompt, provider=provider)
    model = _prompt_with_default(prompt, "Model id", _default_model_for(provider))

    # 3. Install local tools? Hard gate on Linux + GPU + disk if yes.
    install_choice = _prompt_yes_no(
        prompt,
        "Install local GPU tools (RFdiffusion, ProteinMPNN, ColabFold)?",
        default=False,
    )

    install_ran = False
    install_returncode: int | None = None
    install_root: Path | None = None

    if install_choice:
        _gate_on_system_readiness()
        install_root = Path(
            _prompt_with_default(prompt, "Install directory", str(DEFAULT_INSTALL_PREFIX))
        ).expanduser()
        install_returncode = runner(
            [
                "bash",
                str(SETUP_SCRIPT),
            ]
        )
        install_ran = True
        if install_returncode != 0:
            c.err(
                f"install script exited with code {install_returncode}. "
                "Fix the failure and re-run `proteinclaw setup`."
            )
            raise SystemExit(install_returncode)
        c.ok("install script completed")
    else:
        c.warn(
            "Skipping local tool install. RFdiffusion / ProteinMPNN will fail at "
            "first use unless you set them up later."
        )

    # 4. Persist.
    config = Config(
        ai_provider=provider,
        ai_api_key=api_key,
        ai_model=model,
        tools_installed=install_ran,
        tools_install_root=str(install_root) if install_root else None,
        env_file=str(Path.home() / ".proteinclaw_env") if install_ran else None,
    )
    path = save_config(config)
    c.ok(f"config saved to {path} (mode 600)")
    if install_ran:
        c.info(f"source the env file before running: source {Path.home() / '.proteinclaw_env'}")
    return WizardResult(
        config=config,
        install_ran=install_ran,
        install_returncode=install_returncode,
    )


def _gate_on_system_readiness() -> None:
    """Run the doctor checks; abort the wizard if anything important fails."""
    report = run_doctor()
    blocking = [
        ck
        for ck in report.checks
        if ck.status is CheckStatus.FAIL and ck.name in {"OS", "NVIDIA GPU", "Free disk (home)"}
    ]
    if blocking:
        c.err("System is not ready for a local GPU install:")
        for ck in blocking:
            c.err(f"  - {ck.name}: {ck.detail}")
            if ck.fix_hint:
                c.info(f"    fix: {ck.fix_hint}")
        c.info("Re-run setup after fixing, or skip the install step.")
        raise SystemExit(1)


def _prompt_for_api_key(prompt: PromptFn, secret_prompt: SecretPromptFn) -> str:
    """Read the API key — preferring an existing env var, else prompt."""
    env_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    if env_key and _prompt_yes_no(
        prompt,
        "ANTHROPIC_API_KEY is set in your env. Use it?",
        default=True,
    ):
        return env_key
    while True:
        key = secret_prompt("Anthropic API key: ").strip()
        if key:
            return key
        c.warn("API key cannot be empty.")


def _prompt_provider(prompt: PromptFn) -> str:
    """Read the hosted LLM provider."""
    while True:
        provider = _prompt_with_default(
            prompt,
            "AI provider (openrouter/anthropic/gemini)",
            "openrouter",
        )
        provider = provider.strip().lower()
        if provider in {"anthropic", "gemini", "openrouter"}:
            return provider
        c.warn("Provider must be 'openrouter', 'anthropic', or 'gemini'.")


def _default_model_for(provider: str) -> str:
    """Return the default model id for a supported provider."""
    if provider == "openrouter":
        return "google/gemini-2.5-flash"
    if provider == "gemini":
        return "gemini-2.5-flash"
    return "claude-sonnet-4-6"


def _api_key_env_var(provider: str) -> str:
    """Return the API key environment variable for a supported provider."""
    if provider == "openrouter":
        return "OPENROUTER_API_KEY"
    if provider == "gemini":
        return "GEMINI_API_KEY"
    return "ANTHROPIC_API_KEY"


def _prompt_for_provider_api_key(
    prompt: PromptFn,
    secret_prompt: SecretPromptFn,
    *,
    provider: str,
) -> str:
    """Read the API key, preferring an existing provider-specific env var."""
    env_var = _api_key_env_var(provider)
    env_key = os.environ.get(env_var) or ""
    if env_key and _prompt_yes_no(
        prompt,
        f"{env_var} is set in your env. Use it?",
        default=True,
    ):
        return env_key
    while True:
        label = {
            "openrouter": "OpenRouter API key",
            "gemini": "Gemini API key",
        }.get(provider, "Anthropic API key")
        key = secret_prompt(f"{label}: ").strip()
        if key:
            return key
        c.warn("API key cannot be empty.")


def _prompt_yes_no(prompt: PromptFn, question: str, *, default: bool) -> bool:
    """Yes/no with a default. Accepts y, yes, n, no in any case."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = prompt(f"{question} {suffix} ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        c.warn("Please answer y or n.")


def _prompt_with_default(prompt: PromptFn, label: str, default: str) -> str:
    """Read a string, falling back to `default` on empty input."""
    raw = prompt(f"{label} [{default}]: ").strip()
    return raw or default


def _default_runner(argv: list[str]) -> int:
    """Default install-script runner. Inherits stdio so the user sees progress."""
    if not shutil.which(argv[0]):
        c.err(f"{argv[0]} not on PATH")
        return 127
    return subprocess.run(argv, check=False).returncode

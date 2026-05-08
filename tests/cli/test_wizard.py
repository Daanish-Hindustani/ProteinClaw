"""Tests for cli/wizard.py — interactive setup with mocked I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from proteinclaw.cli import config as config_mod
from proteinclaw.cli import wizard


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dir = tmp_path / ".proteinclaw"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", fake_dir / "config.json")


class _Prompter:
    """Yields canned answers in order; raises if exhausted."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.calls: list[str] = []

    def __call__(self, _label: str) -> str:
        self.calls.append(_label)
        if not self._answers:
            raise AssertionError(f"prompt called with no answer left for: {_label!r}")
        return self._answers.pop(0)


def test_wizard_skips_install_writes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prompter = _Prompter(
        [
            "claude-sonnet-4-6",  # model id (default accepted via empty? we pass explicit)
            "n",  # install local tools? no
        ]
    )
    secret = _Prompter(["sk-ant-test-key"])
    runner_calls: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        runner_calls.append(argv)
        return 0

    result = wizard.run_wizard(prompt=prompter, secret_prompt=secret, runner=runner)
    assert result.install_ran is False
    assert runner_calls == []  # install runner never invoked
    cfg = config_mod.load_config()
    assert cfg.ai_api_key == "sk-ant-test-key"
    assert cfg.tools_installed is False


def test_wizard_uses_env_var_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    prompter = _Prompter(
        [
            "y",  # use env var? yes
            "claude-sonnet-4-6",  # model id
            "n",  # install? no
        ]
    )
    secret = _Prompter([])  # never asked
    result = wizard.run_wizard(
        prompt=prompter,
        secret_prompt=secret,
        runner=lambda _: 0,
    )
    assert result.config.ai_api_key == "sk-from-env"


def test_wizard_install_step_runs_script_and_persists_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Force the readiness gate to pass.
    monkeypatch.setattr(wizard, "_gate_on_system_readiness", lambda: None)
    install_dir = tmp_path / "tools"
    prompter = _Prompter(
        [
            "claude-sonnet-4-6",
            "y",  # install
            str(install_dir),  # install dir
        ]
    )
    secret = _Prompter(["sk-test"])
    runner_calls: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        runner_calls.append(argv)
        return 0

    result = wizard.run_wizard(prompt=prompter, secret_prompt=secret, runner=runner)
    assert result.install_ran is True
    assert runner_calls and "lambda_labs_setup.sh" in runner_calls[0][1]
    cfg = config_mod.load_config()
    assert cfg.tools_installed is True
    assert cfg.tools_install_root == str(install_dir)


def test_wizard_aborts_when_install_script_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(wizard, "_gate_on_system_readiness", lambda: None)
    prompter = _Prompter(
        [
            "claude-sonnet-4-6",
            "y",
            "/tmp/whatever",
        ]
    )
    secret = _Prompter(["sk-test"])
    with pytest.raises(SystemExit) as exc:
        wizard.run_wizard(prompt=prompter, secret_prompt=secret, runner=lambda _: 7)
    assert exc.value.code == 7


def test_wizard_aborts_when_readiness_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def boom() -> None:
        raise SystemExit(1)

    monkeypatch.setattr(wizard, "_gate_on_system_readiness", boom)
    prompter = _Prompter(
        [
            "claude-sonnet-4-6",
            "y",  # install
        ]
    )
    secret = _Prompter(["sk-test"])
    with pytest.raises(SystemExit) as exc:
        wizard.run_wizard(prompt=prompter, secret_prompt=secret)
    assert exc.value.code == 1

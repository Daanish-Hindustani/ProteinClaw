"""Tests for cli/config.py — round-trip, validation, redaction, permissions."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from proteinclaw.cli import config as config_mod


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect ~/.proteinclaw to a tmp_path for every test in this module."""
    fake_dir = tmp_path / ".proteinclaw"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", fake_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", fake_dir / "config.json")


def test_save_and_load_round_trip() -> None:
    cfg = config_mod.Config(
        ai_api_key="sk-ant-1234567890abcdef",
        ai_model="claude-sonnet-4-6",
        tools_installed=True,
        tools_install_root="/opt/proteinclaw",
    )
    path = config_mod.save_config(cfg)
    assert path.is_file()
    loaded = config_mod.load_config()
    assert loaded == cfg


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_save_chmods_to_600() -> None:
    cfg = config_mod.Config(ai_api_key="sk-test")
    path = config_mod.save_config(cfg)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_setup_complete_false_when_missing() -> None:
    assert config_mod.setup_complete() is False


def test_setup_complete_true_after_save() -> None:
    config_mod.save_config(config_mod.Config(ai_api_key="sk-test"))
    assert config_mod.setup_complete() is True


def test_load_raises_on_missing_file() -> None:
    with pytest.raises(config_mod.ConfigError):
        config_mod.load_config()


def test_load_raises_on_invalid_json() -> None:
    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_PATH.write_text("not json", encoding="utf-8")
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load_config()
    assert "valid JSON" in str(exc.value)


def test_load_raises_on_schema_mismatch() -> None:
    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod.CONFIG_PATH.write_text(
        json.dumps({"version": 1, "ai_provider": "anthropic"}),  # missing api key
        encoding="utf-8",
    )
    with pytest.raises(config_mod.ConfigError):
        config_mod.load_config()


def test_redact_masks_long_key() -> None:
    cfg = config_mod.Config(ai_api_key="sk-ant-1234567890abcdef")
    redacted = config_mod.redact(cfg)
    assert "1234567890" not in redacted["ai_api_key"]
    assert "sk-ant" in str(redacted["ai_api_key"])


def test_redact_masks_short_key() -> None:
    cfg = config_mod.Config(ai_api_key="short")
    redacted = config_mod.redact(cfg)
    assert redacted["ai_api_key"] == "…"


def test_env_for_subprocess_includes_key_and_install_root() -> None:
    cfg = config_mod.Config(
        ai_api_key="sk-test",
        tools_installed=True,
        tools_install_root="/opt/x",
    )
    env = config_mod.env_for_subprocess(cfg)
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert env["INSTALL_PREFIX"] == "/opt/x"


def test_env_for_subprocess_uses_gemini_key() -> None:
    cfg = config_mod.Config(
        ai_provider="gemini",
        ai_api_key="gemini-test",
        ai_model="gemini-2.5-flash",
    )
    env = config_mod.env_for_subprocess(cfg)
    assert env["GEMINI_API_KEY"] == "gemini-test"


def test_env_for_subprocess_uses_openrouter_key() -> None:
    cfg = config_mod.Config(
        ai_provider="openrouter",
        ai_api_key="openrouter-test",
        ai_model="google/gemini-2.5-flash",
    )
    env = config_mod.env_for_subprocess(cfg)
    assert env["OPENROUTER_API_KEY"] == "openrouter-test"

"""CLI configuration persisted at ``~/.proteinclaw/config.json``.

The config records the AI provider + key, where local tools were
installed, and a setup-completed timestamp. The file is chmod'd 600 on
write — we store the API key in plain JSON, and the user accepted that
trade-off in the wizard. Dotfile-syncing tools that traverse the home
directory may still pick it up; that's a documented risk.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# XDG-standard config path. We avoid `~/.proteinclaw/config.json` because
# at least one other CLI tool already uses that exact path; sharing it
# would either trample their config or fail to validate ours.
def _xdg_config_home() -> Path:
    """Return ``$XDG_CONFIG_HOME`` or its default ``$HOME/.config``."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config"


CONFIG_DIR = _xdg_config_home() / "proteinclaw"
CONFIG_PATH = CONFIG_DIR / "config.json"
CURRENT_VERSION = 1


class ConfigError(RuntimeError):
    """Raised when the on-disk config is missing or malformed."""


class Config(BaseModel):
    """Persisted CLI configuration.

    Attributes:
        version: Schema version. Bump when adding required fields.
        ai_provider: Currently always ``"anthropic"`` — Claude-only.
        ai_model: Concrete model id (e.g. ``"claude-sonnet-4-6"``).
        ai_api_key: API key. Plaintext on disk by user choice.
        tools_installed: True iff the wizard ran the install step.
        tools_install_root: Where local tools live (mirrors ``$INSTALL_PREFIX``).
        env_file: Path to the shell env file written by the install script.
        setup_completed_at: ISO-8601 UTC timestamp of last successful setup.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = CURRENT_VERSION
    ai_provider: Literal["anthropic"] = "anthropic"
    ai_model: str = "claude-sonnet-4-6"
    ai_api_key: str
    tools_installed: bool = False
    tools_install_root: str | None = None
    env_file: str | None = None
    setup_completed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def config_exists() -> bool:
    """Return True iff a config file is present on disk."""
    return CONFIG_PATH.is_file()


def load_config() -> Config:
    """Load and validate the config from disk.

    Raises:
        ConfigError: If the file is missing, unparseable, or fails schema
            validation. The error message points the user to ``setup``.
    """
    if not CONFIG_PATH.is_file():
        raise ConfigError(f"no config at {CONFIG_PATH}. Run `proteinclaw setup` first.")
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"config at {CONFIG_PATH} is not valid JSON: {e}") from e
    try:
        return Config.model_validate(raw)
    except Exception as e:
        raise ConfigError(f"config at {CONFIG_PATH} failed validation: {e}") from e


def save_config(config: Config) -> Path:
    """Write the config to disk with mode 600.

    Returns the resolved config path so callers can show it to the user.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump_json(indent=2)
    CONFIG_PATH.write_text(payload, encoding="utf-8")
    # Tighten permissions even if mkdir/write left them looser.
    try:
        CONFIG_PATH.chmod(0o600)
        CONFIG_DIR.chmod(0o700)
    except OSError:
        # Windows or weird filesystems — non-fatal.
        pass
    return CONFIG_PATH


def redact(config: Config) -> dict[str, object]:
    """Return a config dump with the API key partially masked for display."""
    raw = config.model_dump()
    key = str(raw.get("ai_api_key") or "")
    if len(key) > 10:
        raw["ai_api_key"] = f"{key[:6]}…{key[-4:]}"
    elif key:
        raw["ai_api_key"] = "…"
    return raw


def setup_complete() -> bool:
    """True iff a config exists and survives validation."""
    if not config_exists():
        return False
    try:
        load_config()
    except ConfigError:
        return False
    return True


def env_for_subprocess(config: Config) -> dict[str, str]:
    """Build the env-var dict to pass to subprocess invocations.

    Layered: process env → tool install paths → API key. Caller can
    override anything by adding their own keys after.
    """
    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = config.ai_api_key
    if config.tools_install_root:
        env.setdefault("INSTALL_PREFIX", config.tools_install_root)
    return env

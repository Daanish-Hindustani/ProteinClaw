"""Codex MCP bridge for ProteinClaw.

This module writes a small managed section into ``~/.codex/config.toml`` so
Codex can launch the ProteinClaw MCP server. The server itself is
agent-agnostic; this helper is only a convenience installer for Codex users.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


MARKER_START = "# managed by ProteinClaw - codex MCP bridge"
MARKER_END = "# end ProteinClaw codex MCP bridge"


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items())
        return "{ " + parts + " }"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def _strip_managed_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_block = False
    for line in lines:
        if line.rstrip("\n") == MARKER_START:
            in_block = True
            continue
        if in_block:
            if line.rstrip("\n") == MARKER_END:
                in_block = False
            continue
        out.append(line)
    return "".join(out).rstrip() + ("\n" if out else "")


def _insert_top_level(user_text: str, managed_block: str) -> str:
    """Insert root-scoped TOML before the first table header."""
    if not user_text.strip():
        return managed_block
    lines = user_text.splitlines(keepends=True)
    first_table = next(
        (idx for idx, line in enumerate(lines) if line.lstrip().startswith("[")),
        None,
    )
    if first_table is None:
        return user_text.rstrip() + "\n\n" + managed_block
    prefix = "".join(lines[:first_table]).rstrip()
    suffix = "".join(lines[first_table:]).lstrip("\n")
    if prefix:
        return prefix + "\n\n" + managed_block + "\n" + suffix
    return managed_block + "\n" + suffix


def _codex_config_path(codex_home: Path | None = None) -> Path:
    home = codex_home or Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return home / "config.toml"


def install_proteinclaw_codex_mcp(
    *,
    run_dir: Path,
    session_id: str,
    host_workspace: Path,
    codex_home: Path | None = None,
) -> Path:
    """Write/update Codex config so app-server sees ProteinClaw tools."""
    config_path = _codex_config_path(codex_home)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    env = {
        "PROTEINCLAW_RUNS_DIR": str(Path(run_dir).resolve().parent),
        "PROTEINCLAW_WORKSPACE_ROOT": str(Path(host_workspace).resolve().parent),
        "PROTEINCLAW_SKIP_DEBUG_TOOLS": "1",
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
    }
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        env["HERMES_HOME"] = hermes_home

    block_lines = [
        MARKER_START,
        'default_permissions = ":workspace"',
        "",
        "[mcp_servers.proteinclaw]",
        f"command = {_toml_value(sys.executable)}",
        f"args = {_toml_value(['-m', 'proteinclaw.agent.mcp_server'])}",
        f"env = {_toml_value(env)}",
        "startup_timeout_sec = 30.0",
        "tool_timeout_sec = 7200.0",
        MARKER_END,
        "",
    ]
    managed_block = "\n".join(block_lines)

    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    stripped = _strip_managed_block(existing)
    config_path.write_text(_insert_top_level(stripped, managed_block), encoding="utf-8")
    return config_path


def uninstall_proteinclaw_codex_mcp(*, codex_home: Path | None = None) -> None:
    """Remove ProteinClaw's managed Codex MCP block if present."""
    config_path = _codex_config_path(codex_home)
    if not config_path.exists():
        return
    existing = config_path.read_text(encoding="utf-8")
    stripped = _strip_managed_block(existing)
    config_path.write_text(stripped, encoding="utf-8")


__all__ = ["install_proteinclaw_codex_mcp", "uninstall_proteinclaw_codex_mcp"]

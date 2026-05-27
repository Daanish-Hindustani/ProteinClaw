"""Shared path helpers for tools that produce on-disk artifacts.

PRD §9.3: every tool writes to a session-keyed workspace and returns *paths*.
GPU tools see ``/workspace`` via a bind mount; plain-Python tools resolve to
``~/.proteinclaw/gpu-workspace/<session_id>/<tool>_<step>/`` on the host.

Plain-Python tools called without a ``session_id`` (e.g. from a REPL / manual
test) write to an ``_adhoc`` subdirectory so artifacts never disappear into
``/tmp`` and stay inspectable after the call.

Per-host caches that persist across runs (downloaded PDBs, lit-search hits)
live under ``~/.cache/proteinclaw/<subkey>/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

DEFAULT_WORKSPACE_ROOT = Path("~/.proteinclaw/gpu-workspace").expanduser()
DEFAULT_CACHE_ROOT = Path("~/.cache/proteinclaw").expanduser()


def session_workspace(session_id: Optional[str]) -> Path:
    """Return the per-session workspace dir; ``_adhoc`` if no session_id."""
    if session_id:
        d = DEFAULT_WORKSPACE_ROOT / session_id
    else:
        d = DEFAULT_WORKSPACE_ROOT / "_adhoc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_output_dir(
    tool_short: str,
    session_id: Optional[str] = None,
    step: int = 0,
) -> Path:
    """Per-tool subdirectory inside the session workspace.

    ``tool_short`` is the part of the tool name after the dot
    (e.g. ``uniprot_fetch`` for ``data.uniprot_fetch``).
    """
    sub = f"{tool_short}_{step}"
    d = session_workspace(session_id) / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool_cache_dir(subkey: str) -> Path:
    """Cross-session host cache directory (e.g. for downloaded PDB files)."""
    d = DEFAULT_CACHE_ROOT / subkey
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_WORKSPACE_ROOT",
    "session_workspace",
    "tool_cache_dir",
    "tool_output_dir",
]

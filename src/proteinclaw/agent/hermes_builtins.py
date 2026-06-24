"""ProteinClaw-owned built-in tools for the Hermes harness.

These are deliberately scoped, in-process tools that run in the **host venv**
with their working root fixed to the run directory. We keep our own file/shell
tools (rather than enabling Hermes' native ``file``/``terminal`` toolsets)
because the agent's structural sandbox relies on biopython being importable in
the host venv and on reading/writing the run dir + the bind-mounted GPU
workspace — guarantees Hermes' sandboxed code tool does not give us.

Web search and skill self-evolution are NOT reimplemented here: the harness
enables Hermes' native ``web`` and ``skills`` toolsets for those.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from proteinclaw.agent.mcp_tools import (
    HERMES_TOOLSET_NAME,
    RESEARCH_TOOLSET_NAME,
    HermesToolSpec,
)


READ_ONLY_NAMES = {"file_read", "file_search"}

_OBJ_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": True}


class ToolPermissionError(PermissionError):
    """Raised when a built-in tool tries to escape its allowed scope."""


def _resolve_under(path: str | Path, root: Path) -> Path:
    root = root.resolve()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ToolPermissionError(f"path {p} is outside allowed root {root}")
    return p


def _file_read(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_under(args.get("path") or args.get("file_path") or "", root)
        max_chars = int(args.get("max_chars") or 100_000)
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": str(path), "text": text[:max_chars], "truncated": len(text) > max_chars}
    return _handler


def _file_write(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_under(args.get("path") or args.get("file_path") or "", root)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = str(args.get("content") or "")
        append = bool(args.get("append", False))
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            fh.write(content)
        return {"path": str(path), "bytes": len(content.encode("utf-8")), "append": append}
    return _handler


def _file_patch(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_under(args.get("path") or args.get("file_path") or "", root)
        old = str(args.get("old") or "")
        new = str(args.get("new") or "")
        if not old:
            raise ValueError("file_patch requires non-empty 'old' text")
        text = path.read_text(encoding="utf-8")
        count = int(args.get("count") or 1)
        if old not in text:
            raise ValueError("old text not found")
        path.write_text(text.replace(old, new, count), encoding="utf-8")
        return {"path": str(path), "replacements": min(count, text.count(old))}
    return _handler


def _file_search(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern") or args.get("query") or "")
        if not pattern:
            raise ValueError("file_search requires pattern")
        max_results = int(args.get("max_results") or 50)
        matches: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pattern in line:
                        matches.append({"path": str(path), "line": i, "text": line})
                        if len(matches) >= max_results:
                            return {"matches": matches}
            except OSError:
                continue
        return {"matches": matches}
    return _handler


def _shell_exec(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        cmd = str(args.get("command") or "")
        if not cmd:
            raise ValueError("shell_exec requires command")
        timeout = int(args.get("timeout_s") or 120)
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-100_000:],
            "stderr": proc.stderr[-100_000:],
        }
    return _handler


def _research_scout(factory: Optional[Callable[[str, str], Any]]) -> Callable[[dict[str, Any]], Any]:
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        task = str(args.get("task") or args.get("description") or "")
        scout_type = str(args.get("scout_type") or "research")
        if factory is None:
            return {"error": "research_scout_unconfigured", "summary": "No scout factory was configured.", "task": task}
        result = factory(scout_type, task)
        if asyncio.iscoroutine(result):
            result = await result
        return {"scout_type": scout_type, "task": task, "result": result}
    return _handler


def build_builtin_specs(
    *,
    run_dir: Path,
    read_only: bool = False,
    research_scout_factory: Optional[Callable[[str, str], Any]] = None,
) -> list[HermesToolSpec]:
    """Return scoped built-in tool specs for a run.

    Reads (``file_read``/``file_search``) go in the read-only research toolset
    so scouts may use them; writes/shell/scout-spawn go in the privileged
    ``proteinclaw`` toolset. ``read_only=True`` returns only the read tools.
    """
    run_dir = run_dir.resolve()
    specs: list[HermesToolSpec] = [
        HermesToolSpec("file_read", "Read a UTF-8 file under the run directory.", _OBJ_SCHEMA, _file_read(run_dir), RESEARCH_TOOLSET_NAME),
        HermesToolSpec("file_search", "Search text files under the run directory.", _OBJ_SCHEMA, _file_search(run_dir), RESEARCH_TOOLSET_NAME),
    ]
    if not read_only:
        specs.extend([
            HermesToolSpec("file_write", "Write a UTF-8 file under the run directory.", _OBJ_SCHEMA, _file_write(run_dir), HERMES_TOOLSET_NAME),
            HermesToolSpec("file_patch", "Replace exact text in a run-directory file.", _OBJ_SCHEMA, _file_patch(run_dir), HERMES_TOOLSET_NAME),
            HermesToolSpec("shell_exec", "Run a shell command with cwd fixed to the run directory (host venv).", _OBJ_SCHEMA, _shell_exec(run_dir), HERMES_TOOLSET_NAME),
            HermesToolSpec("research_scout", "Spawn a read-only Hermes research scout (PROPOSE/DEFEND debate partner).", _OBJ_SCHEMA, _research_scout(research_scout_factory), HERMES_TOOLSET_NAME),
        ])
    return specs


__all__ = ["READ_ONLY_NAMES", "ToolPermissionError", "build_builtin_specs"]

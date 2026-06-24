"""ProteinClaw-owned built-in tools for the Hermes harness."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from proteinclaw.agent.hermes_harness import HermesAgentOptions, HermesHarness
from proteinclaw.agent.mcp_tools import HERMES_TOOLSET_NAME, HermesToolSpec


READ_ONLY_NAMES = {"file_read", "file_search", "web_search", "web_fetch"}


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


def _web_unavailable(kind: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "error": "web_tool_unavailable",
            "summary": f"{kind} is provided by the live Hermes environment; local test harness has no network browser.",
            "input": args,
        }
    return _handler


def build_builtin_toolset(
    *,
    run_dir: Path,
    skills_dir: Optional[Path] = None,
    read_only: bool = False,
    research_scout_factory: Optional[Callable[[str, str], Any]] = None,
) -> dict[str, Any]:
    """Return scoped built-ins for a run.

    Writes are limited to ``run_dir``. Skill evolution is intentionally not a
    direct file write path; the prompt directs Hermes to use ``skill_manage``.
    """
    run_dir = run_dir.resolve()
    specs: list[HermesToolSpec] = [
        HermesToolSpec("file_read", "Read a UTF-8 file under the run directory.", {"type": "object"}, _file_read(run_dir)),
        HermesToolSpec("file_search", "Search text files under the run directory.", {"type": "object"}, _file_search(run_dir)),
        HermesToolSpec("web_search", "Search the web for scientific literature context.", {"type": "object"}, _web_unavailable("web_search")),
        HermesToolSpec("web_fetch", "Fetch a URL for scientific literature context.", {"type": "object"}, _web_unavailable("web_fetch")),
    ]
    if not read_only:
        specs.extend([
            HermesToolSpec("file_write", "Write a UTF-8 file under the run directory.", {"type": "object"}, _file_write(run_dir)),
            HermesToolSpec("file_patch", "Replace exact text in a run-directory file.", {"type": "object"}, _file_patch(run_dir)),
            HermesToolSpec("shell_exec", "Run a shell command with cwd fixed to the run directory.", {"type": "object"}, _shell_exec(run_dir)),
        ])
        specs.append(HermesToolSpec("research_scout", "Spawn a read-only Hermes research scout.", {"type": "object"}, _research_scout(research_scout_factory)))
    return {"name": f"{HERMES_TOOLSET_NAME}_builtins", "tools": specs}


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


__all__ = ["READ_ONLY_NAMES", "ToolPermissionError", "build_builtin_toolset"]

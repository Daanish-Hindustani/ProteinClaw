"""Runtime helpers for local protein-design Docker tools."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home


DEFAULT_FOUNDRY_IMAGE = "rosettacommons/foundry:latest"
DEFAULT_ESMFOLD_IMAGE = "hermes-esmfold:latest"


def config_value(name: str, default: Any) -> Any:
    """Read a `protein_design.*` config value, falling back to env/default."""
    env_name = "HERMES_PROTEIN_" + name.upper()
    if env_name in os.environ:
        return os.environ[env_name]
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        section = cfg.get("protein_design") or {}
        if isinstance(section, dict) and name in section:
            return section[name]
    except Exception:
        pass
    return default


def plugin_workspace() -> Path:
    raw = config_value("workspace_root", "")
    if raw:
        return Path(str(raw)).expanduser().resolve()
    return (get_hermes_home() / "protein-design").resolve()


def check_docker_requirements() -> bool:
    return shutil.which("docker") is not None


def ensure_workspace(path: Path | None = None) -> Path:
    root = (path or plugin_workspace()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_workspace_path(path: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a user path and optionally assert it exists.

    Relative paths are resolved against the current process CWD because ProteinClaw
    CLI tools already use CWD as workspace context.
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()
    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")
    return p


def common_mount_root(paths: list[Path], fallback: Path | None = None) -> Path:
    existing = [p if p.is_dir() else p.parent for p in paths if p]
    if not existing:
        return ensure_workspace(fallback)
    try:
        return Path(os.path.commonpath([str(p.resolve()) for p in existing])).resolve()
    except ValueError:
        return ensure_workspace(fallback)


def to_container_path(path: Path, mount_root: Path) -> str:
    return "/work/" + str(path.resolve().relative_to(mount_root.resolve()))


def run_docker(
    image: str,
    args: list[str],
    *,
    mount_root: Path,
    timeout: int | None = None,
    gpus: bool = True,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    timeout = int(timeout or config_value("default_timeout_seconds", 3600))
    command = ["docker", "run", "--rm"]
    if gpus:
        command.extend(["--gpus", "all"])
    for key, value in (env or {}).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend(["-v", f"{mount_root.resolve()}:/work", "-w", "/work", image])
    command.extend(args)

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "success": completed.returncode == 0,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


def json_result(**payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)

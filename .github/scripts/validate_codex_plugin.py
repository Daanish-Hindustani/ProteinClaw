#!/usr/bin/env python3
"""Validate the repository's Codex plugin package.

This mirrors the local Codex plugin validator checks needed by CI without
depending on a developer-specific Codex installation path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


REQUIRED_INTERFACE_FIELDS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
}


def _fail(message: str) -> None:
    raise SystemExit(f"Codex plugin validation failed: {message}")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    manifest_path = root / ".codex-plugin" / "plugin.json"
    if not manifest_path.exists():
        _fail("missing .codex-plugin/plugin.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in ("name", "version", "description", "author", "skills", "mcpServers", "interface"):
        if field not in manifest:
            _fail(f"plugin.json missing {field!r}")
    if manifest["name"] != root.name.lower().replace("_", "-"):
        _fail("plugin name must match repository/plugin folder name")
    if manifest["skills"] != "./skills/":
        _fail("plugin skills path must be ./skills/")
    if manifest["mcpServers"] != "./.mcp.json":
        _fail("plugin MCP path must be ./.mcp.json")

    interface = manifest["interface"]
    missing_interface = sorted(REQUIRED_INTERFACE_FIELDS - set(interface))
    if missing_interface:
        _fail(f"plugin interface missing {missing_interface}")

    mcp_path = root / ".mcp.json"
    if not mcp_path.exists():
        _fail("missing .mcp.json")
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    server = mcp.get("mcpServers", {}).get("proteinclaw")
    if not server:
        _fail(".mcp.json missing proteinclaw server")
    if server.get("command") != "uv":
        _fail("proteinclaw MCP server must launch with uv")

    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    if not skill_files:
        _fail("no packaged skills found")
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            _fail(f"{skill_file} missing YAML frontmatter")
        try:
            _, frontmatter, _ = text.split("---", 2)
            data = yaml.safe_load(frontmatter)
        except Exception as exc:  # noqa: BLE001
            _fail(f"{skill_file} frontmatter is invalid YAML: {exc}")
        if not isinstance(data, dict):
            _fail(f"{skill_file} frontmatter must be a mapping")
        if data.get("name") != skill_file.parent.name:
            _fail(f"{skill_file} frontmatter name must match directory")
        if not str(data.get("description") or "").strip():
            _fail(f"{skill_file} frontmatter needs a description")
    print(f"Codex plugin validation passed: {root}")


if __name__ == "__main__":
    main()

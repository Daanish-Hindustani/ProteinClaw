from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_codex_plugin_points_to_repo_native_mcp_and_skill() -> None:
    plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert plugin["name"] == "proteinclaw"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert plugin["skills"] == "./skills/"
    skill_root = ROOT / "skills"
    assert (skill_root / "proteinclaw-workflow" / "SKILL.md").exists()
    assert (skill_root / "proteinclaw-minibinder" / "SKILL.md").exists()
    assert (skill_root / "proteinclaw-nanobody" / "SKILL.md").exists()

    workflow = (skill_root / "proteinclaw-workflow" / "SKILL.md").read_text(encoding="utf-8")
    assert "proteinclaw_research_record" in workflow
    assert "proteinclaw_debate_record" in workflow

    server = mcp["mcpServers"]["proteinclaw"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "--project", ".", "python", "-m", "proteinclaw.agent.mcp_server"]


def test_codex_docs_cover_plugin_runtime() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "Codex" in readme
    assert "python -m proteinclaw.agent.mcp_server" in readme
    assert ".codex-plugin/plugin.json" in readme
    assert "MCP server" in architecture
    assert "proteinclaw_research_record" in readme
    assert "Claude" not in readme


def test_all_packaged_skill_frontmatter_is_valid_yaml() -> None:
    for skill_file in sorted((ROOT / "skills").glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{skill_file} missing frontmatter"
        try:
            _, frontmatter, _ = text.split("---", 2)
        except ValueError as exc:
            raise AssertionError(f"{skill_file} has malformed frontmatter") from exc
        data = yaml.safe_load(frontmatter)
        assert isinstance(data, dict), f"{skill_file} frontmatter must be a mapping"
        assert data.get("name") == skill_file.parent.name
        assert isinstance(data.get("description"), str) and data["description"].strip()


def test_generated_runs_are_not_tracked() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("tracked file check requires a git checkout")
    result = subprocess.run(
        ["git", "ls-files", "runs", "runs_external_mor.log"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    assert not tracked, f"generated runtime artifacts are tracked: {tracked[:10]}"

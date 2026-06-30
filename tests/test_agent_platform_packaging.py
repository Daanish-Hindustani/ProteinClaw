from __future__ import annotations

import json
from pathlib import Path


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


def test_agent_install_docs_cover_codex_and_claude_code() -> None:
    text = (ROOT / "docs" / "agent-platform-install.md").read_text(encoding="utf-8")

    assert "Codex" in text
    assert "Claude Code" in text
    assert "python -m proteinclaw.agent.mcp_server" in text
    assert "proteinclaw_research_record" in text
    assert "proteinclaw_debate_record" in text

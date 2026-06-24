"""Hermes scout + options-builder wiring (no live model call)."""

from __future__ import annotations

from proteinclaw.agent.core import _build_options, _research_agents
from proteinclaw.agent.mcp_tools import mcp_tool_name


def test_research_agent_is_read_only_hermes_scout() -> None:
    agents = _research_agents()
    assert "research" in agents
    scout = agents["research"]

    assert scout.model == "anthropic/claude-sonnet-4.6"

    tools = set(scout.tools or [])
    assert mcp_tool_name("research.literature_search") in tools
    assert mcp_tool_name("research.pubmed_search") in tools
    assert {"WebSearch", "WebFetch"} <= tools

    assert "Bash" not in tools
    assert "Write" not in tools
    assert not any("design_" in t or "structure_" in t for t in tools)

    assert "PROPOSE" in scout.prompt
    assert "DEFEND" in scout.prompt


def test_research_pro_is_escalation_tier() -> None:
    agents = _research_agents()
    assert "research_pro" in agents
    pro = agents["research_pro"]
    assert pro.model == "anthropic/claude-opus-4.7"
    assert set(pro.tools or []) == set(agents["research"].tools or [])
    assert pro.prompt == agents["research"].prompt
    assert "Bash" not in (pro.tools or []) and "Write" not in (pro.tools or [])


def test_build_options_research_fanout_on() -> None:
    toolsets = [{"name": "proteinclaw", "tools": []}]
    opts = _build_options(
        extra_system_prompt="x",
        toolsets=toolsets,
        model="anthropic/claude-sonnet-4.6",
        max_turns=10,
        cwd="/tmp",
        session_id="s1",
        research_fanout=True,
    )
    assert opts.ephemeral_system_prompt == "x"
    assert opts.model == "anthropic/claude-sonnet-4.6"
    assert opts.max_iterations == 10
    assert opts.session_id == "s1"
    assert opts.enabled_toolsets == ["proteinclaw"]
    assert opts.research_scouts is not None
    assert "research" in opts.research_scouts
    assert "research_pro" in opts.research_scouts


def test_build_options_research_fanout_off() -> None:
    opts = _build_options(
        extra_system_prompt="x",
        toolsets=[],
        model="anthropic/claude-sonnet-4.6",
        max_turns=10,
        cwd="/tmp",
        session_id="s1",
        research_fanout=False,
    )
    assert opts.research_scouts is None

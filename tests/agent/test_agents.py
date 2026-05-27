"""Research scout subagent + options-builder wiring (no GPU, no SDK call)."""

from __future__ import annotations

from proteinclaw.agent.core import _build_options, _research_agents
from proteinclaw.agent.mcp_tools import MCP_SERVER_NAME, mcp_tool_name


def test_research_agent_is_read_only_sonnet_scout() -> None:
    agents = _research_agents()
    assert "research" in agents
    scout = agents["research"]

    assert scout.model == "sonnet"
    assert MCP_SERVER_NAME in (scout.mcpServers or [])

    tools = set(scout.tools or [])
    # Has both literature MCP tools + the native web tools.
    assert mcp_tool_name("research.literature_search") in tools
    assert mcp_tool_name("research.pubmed_search") in tools
    assert {"WebSearch", "WebFetch"} <= tools

    # Physically barred from the pipeline + from writing deliverables.
    assert "Bash" not in tools
    assert "Write" not in tools
    assert not any(t.startswith(mcp_tool_name("design.")[:-1]) for t in tools)
    assert not any("design_" in t or "structure_" in t for t in tools)

    # Dual-mode debate partner.
    assert "PROPOSE" in scout.prompt
    assert "DEFEND" in scout.prompt


def test_research_pro_is_opus_escalation_tier() -> None:
    """Refused Sonnet scouts escalate to an Opus tier (verified: Opus answers
    immune-checkpoint residue queries that Sonnet refuses)."""
    agents = _research_agents()
    assert "research_pro" in agents
    pro = agents["research_pro"]
    assert pro.model == "claude-opus-4-7"
    # Same read-only surface as the Sonnet scout — only the model differs.
    assert set(pro.tools or []) == set(agents["research"].tools or [])
    assert pro.prompt == agents["research"].prompt
    assert "Bash" not in (pro.tools or []) and "Write" not in (pro.tools or [])


def test_build_options_research_fanout_on() -> None:
    opts = _build_options(
        extra_system_prompt="x",
        mcp_server=object(),
        model="claude-opus-4-7",
        max_turns=10,
        cwd="/tmp",
        research_fanout=True,
    )
    # Runtime SDK names the spawn tool "Agent"; older docs say "Task". Allow both.
    assert "Agent" in opts.allowed_tools
    assert "Task" in opts.allowed_tools
    assert opts.agents is not None
    assert "research" in opts.agents
    assert "research_pro" in opts.agents


def test_build_options_research_fanout_off() -> None:
    opts = _build_options(
        extra_system_prompt="x",
        mcp_server=object(),
        model="claude-opus-4-7",
        max_turns=10,
        cwd="/tmp",
        research_fanout=False,
    )
    assert "Agent" not in opts.allowed_tools
    assert "Task" not in opts.allowed_tools
    assert opts.agents is None

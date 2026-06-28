"""Hermes scout + harness wiring.

Mixes pure-unit coverage (fake AIAgent with the real callback/return contract)
with a real-integration check that ProteinClaw specs registered into Hermes'
actual ``model_tools.registry`` are exposed by ``get_tool_definitions`` — the
exact path that was silently broken before the harness rewrite.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from proteinclaw.agent.core import _build_options, _research_agents
from proteinclaw.agent.hermes_harness import HermesAgentOptions, HermesHarness
from proteinclaw.agent.mcp_tools import (
    HERMES_TOOLSET_NAME,
    RESEARCH_TOOLSET_NAME,
    mcp_tool_name,
    proteinclaw_tool_specs,
)


# --------------------------------------------------------------------------- #
# Research scouts                                                             #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Options builder                                                             #
# --------------------------------------------------------------------------- #


def test_build_options_research_fanout_on() -> None:
    specs = proteinclaw_tool_specs()
    opts = _build_options(
        extra_system_prompt="x",
        specs=specs,
        enabled_toolsets=[HERMES_TOOLSET_NAME, RESEARCH_TOOLSET_NAME, "web", "skills"],
        model="anthropic/claude-sonnet-4.6",
        max_turns=10,
        session_id="s1",
        research_fanout=True,
    )
    assert opts.ephemeral_system_prompt == "x"
    assert opts.model == "anthropic/claude-sonnet-4.6"
    assert opts.max_iterations == 10
    assert opts.session_id == "s1"
    assert opts.specs is specs
    assert opts.enabled_toolsets == [HERMES_TOOLSET_NAME, RESEARCH_TOOLSET_NAME, "web", "skills"]
    assert opts.research_scouts is not None
    assert {"research", "research_pro"} <= set(opts.research_scouts)


def test_build_options_research_fanout_off() -> None:
    opts = _build_options(
        extra_system_prompt="x",
        specs=[],
        enabled_toolsets=[HERMES_TOOLSET_NAME],
        model="anthropic/claude-sonnet-4.6",
        max_turns=10,
        session_id="s1",
        research_fanout=False,
    )
    assert opts.research_scouts is None


# --------------------------------------------------------------------------- #
# Harness drive — fake AIAgent with the REAL callback + return contract        #
# --------------------------------------------------------------------------- #


class _FakeAIAgent:
    """Mimics ``run_agent.AIAgent`` closely enough to verify our wiring.

    On ``run_conversation`` it fires the same callbacks Hermes fires (tool
    start/complete, interim assistant text, reasoning) and returns the real
    result-dict keys (``final_response``/``api_calls``/``estimated_cost_usd``).
    """

    last_kwargs: dict = {}

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs
        self._cb = kwargs

    def run_conversation(self, user_message: str):
        self._cb["reasoning_callback"]("let me think")
        self._cb["tool_start_callback"]("call-1", "mcp__proteinclaw_tools__pdb_fetch", {"pdb_id": "1UBQ"})
        self._cb["tool_complete_callback"]("call-1", "pdb_fetch", {"pdb_id": "1UBQ"}, '{"summary": "ok"}')
        self._cb["interim_assistant_callback"]("here is the plan", False)
        return {
            "final_response": "done",
            "api_calls": 3,
            "estimated_cost_usd": 0.012,
            "session_id": user_message and "sess-1",
            "completed": True,
        }

    def close(self) -> None:  # exercised by the harness cleanup path
        pass


def test_harness_wires_callbacks_to_events_and_maps_summary() -> None:
    events: list[dict] = []
    opts = HermesAgentOptions(
        ephemeral_system_prompt="sys",
        model="anthropic/claude-sonnet-4.6",
        max_iterations=5,
        session_id="sess-1",
        enabled_toolsets=[HERMES_TOOLSET_NAME],
        specs=[],
    )
    harness = HermesHarness(opts, agent_cls=_FakeAIAgent, hermes_registry=object(), register=False)
    summary = asyncio.run(harness.run("design a binder", on_event=events.append))

    # Constructor got the real kwargs (and NOT the dead tools=/toolsets=/cwd=).
    kw = _FakeAIAgent.last_kwargs
    assert kw["enabled_toolsets"] == [HERMES_TOOLSET_NAME]
    assert kw["ephemeral_system_prompt"] == "sys"
    assert "tools" not in kw and "toolsets" not in kw and "cwd" not in kw

    types = [e["type"] for e in events]
    assert types == ["thinking", "tool_use", "tool_result", "assistant_text"]
    assert events[1]["name"] == "mcp__proteinclaw_tools__pdb_fetch"
    assert events[1]["input"] == {"pdb_id": "1UBQ"}

    assert summary["final_text"] == "done"
    assert summary["num_turns"] == 3
    assert summary["total_cost_usd"] == 0.012


def test_harness_installs_codex_mcp_for_codex_models(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    opts = HermesAgentOptions(
        ephemeral_system_prompt="sys",
        model="gpt-5.1-codex",
        max_iterations=5,
        session_id="sess-1",
        cwd=str(tmp_path / "run"),
        host_workspace=str(tmp_path / "workspace"),
        enabled_toolsets=[HERMES_TOOLSET_NAME],
        specs=[],
    )
    harness = HermesHarness(opts, agent_cls=_FakeAIAgent, hermes_registry=object(), register=False)
    harness._instantiate_agent(None)

    kw = _FakeAIAgent.last_kwargs
    assert kw["provider"] == "openai-codex"
    assert kw["api_mode"] == "codex_app_server"
    assert kw["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert kw["api_key"] == "codex-cli-oauth"
    config = tmp_path / "codex" / "config.toml"
    text = config.read_text(encoding="utf-8")
    assert "[mcp_servers.proteinclaw]" in text
    assert "proteinclaw.agent.mcp_server" in text


def test_harness_registers_specs_into_injected_registry() -> None:
    class _Reg:
        def __init__(self) -> None:
            self.calls = 0

        def register(self, **kwargs) -> None:
            self.calls += 1

    reg = _Reg()
    opts = HermesAgentOptions(
        ephemeral_system_prompt="sys",
        model="m",
        max_iterations=1,
        session_id="s",
        enabled_toolsets=[HERMES_TOOLSET_NAME],
        specs=proteinclaw_tool_specs(),
    )
    HermesHarness(opts, agent_cls=_FakeAIAgent, hermes_registry=reg, register=True)
    assert reg.calls == len(opts.specs) > 0


# --------------------------------------------------------------------------- #
# REAL hermes registry — proves registration actually exposes our tools        #
# --------------------------------------------------------------------------- #


def test_real_hermes_registry_exposes_proteinclaw_tools() -> None:
    """Register ProteinClaw specs into the actual model_tools.registry and
    confirm get_tool_definitions surfaces them under our toolset name."""
    model_tools = pytest.importorskip("model_tools")
    from proteinclaw.agent.mcp_tools import register_specs

    specs = proteinclaw_tool_specs()
    register_specs(model_tools.registry, specs)

    defs = model_tools.get_tool_definitions(enabled_toolsets=[HERMES_TOOLSET_NAME])
    exposed = {d.get("function", {}).get("name") for d in defs}
    assert mcp_tool_name("design.proteinmpnn") in exposed
    # Retrieval tools live in the separate research toolset.
    assert mcp_tool_name("research.pubmed_search") not in exposed

    research_defs = model_tools.get_tool_definitions(enabled_toolsets=[RESEARCH_TOOLSET_NAME])
    research_exposed = {d.get("function", {}).get("name") for d in research_defs}
    assert mcp_tool_name("research.pubmed_search") in research_exposed

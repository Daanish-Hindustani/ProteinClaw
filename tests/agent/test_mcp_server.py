from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp.types import CallToolRequest, CallToolRequestParams

from proteinclaw.agent.codex_mcp import (
    install_proteinclaw_codex_mcp,
    uninstall_proteinclaw_codex_mcp,
)
from proteinclaw.agent.mcp_server import _build_specs, build_server
from proteinclaw.agent.run_manager import RunManager


def _call(server, name: str, arguments: dict) -> str:
    handler = server.request_handlers[CallToolRequest]
    result = asyncio.run(
        handler(CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments)))
    )
    return result.root.content[0].text


def test_install_proteinclaw_codex_mcp_writes_managed_config(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    config = codex_home / "config.toml"
    codex_home.mkdir()
    config.write_text("[user]\nkeep = true\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    written = install_proteinclaw_codex_mcp(
        run_dir=tmp_path / "runs" / "r1",
        session_id="sess-1",
        host_workspace=tmp_path / "workspace" / "sess-1",
    )

    text = written.read_text(encoding="utf-8")
    assert written == config
    assert "[user]\nkeep = true" in text
    assert "[mcp_servers.proteinclaw]" in text
    assert "proteinclaw.agent.mcp_server" in text
    assert "PROTEINCLAW_RUNS_DIR" in text
    assert "PROTEINCLAW_WORKSPACE_ROOT" in text
    assert 'default_permissions = ":workspace"' in text
    assert 'web_search = "cached"' not in text


def test_install_proteinclaw_codex_mcp_replaces_prior_block(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    install_proteinclaw_codex_mcp(
        run_dir=tmp_path / "runs1" / "run",
        session_id="old",
        host_workspace=tmp_path / "workspace1" / "old",
    )
    install_proteinclaw_codex_mcp(
        run_dir=tmp_path / "runs2" / "run",
        session_id="new",
        host_workspace=tmp_path / "workspace2" / "new",
    )

    text = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert "runs1" not in text
    assert "runs2" in text
    assert text.count("[mcp_servers.proteinclaw]") == 1


def test_uninstall_proteinclaw_codex_mcp_removes_only_managed_block(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_proteinclaw_codex_mcp(
        run_dir=tmp_path / "run",
        session_id="sess",
        host_workspace=tmp_path / "workspace",
    )
    config = codex_home / "config.toml"
    config.write_text(config.read_text(encoding="utf-8") + "\n[user]\nkeep = true\n", encoding="utf-8")

    uninstall_proteinclaw_codex_mcp()

    text = config.read_text(encoding="utf-8")
    assert "[mcp_servers.proteinclaw]" not in text
    assert "[user]\nkeep = true" in text


def test_mcp_server_exposes_agent_native_tool_surface(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    names = {spec.name for spec in _build_specs(manager)}

    assert "proteinclaw_run_create" in names
    assert "proteinclaw_run_status" in names
    assert "proteinclaw_run_list" in names
    assert "proteinclaw_run_resume" in names
    assert "proteinclaw_run_finalize" in names
    assert "proteinclaw_skill_append" in names
    assert "proteinclaw_skill_create" in names
    assert "proteinclaw_research_record" in names
    assert "proteinclaw_debate_record" in names
    assert "proteinclaw_report_generate" in names
    assert "mcp__proteinclaw_tools__data_pdb_analyze" in names
    assert "mcp__proteinclaw_tools__design_rfdiffusion3" in names
    assert "research_scout" not in names
    assert "web_search" not in names


def test_workflow_record_tools_write_trace_and_artifacts(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    server = build_server(manager)
    json.loads(_call(server, "proteinclaw_run_create", {"prompt": "design", "run_id": "r1"}))

    research = json.loads(_call(server, "proteinclaw_research_record", {
        "run_id": "r1",
        "source": "native_web",
        "query": "ubiquitin de novo binder design",
        "summary": "Native web search found ubiquitin binder examples.",
        "citations": [{"title": "example", "url": "https://example.org"}],
    }))
    debate = json.loads(_call(server, "proteinclaw_debate_record", {
        "run_id": "r1",
        "subagent_type": "native_subagent",
        "prompt": "Critique hotspot choice.",
        "summary": "Hotspots are plausible for smoke testing only.",
        "decision": "proceed",
    }))

    assert Path(research["path"]).name == "research.jsonl"
    assert Path(debate["path"]).name == "debate.jsonl"
    ctx = manager.get_run("r1")
    assert "ubiquitin de novo binder" in (ctx.output_dir / "research.jsonl").read_text(encoding="utf-8")
    assert "Critique hotspot choice" in (ctx.output_dir / "debate.jsonl").read_text(encoding="utf-8")
    assert "Native Research Record" in ctx.plan_md.read_text(encoding="utf-8")

    events = [json.loads(line) for line in ctx.trace_jsonl.read_text(encoding="utf-8").splitlines()]
    assert any(event.get("type") == "research_record" for event in events)
    assert any(event.get("type") == "debate_record" for event in events)


def test_mcp_lifecycle_call_traces_under_created_run(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    server = build_server(manager)

    created = json.loads(_call(server, "proteinclaw_run_create", {"prompt": "design", "run_id": "r1"}))
    status = json.loads(_call(server, "proteinclaw_run_status", {"run_id": "r1"}))

    assert created["run_id"] == "r1"
    assert status["status"] == "created"
    trace = Path(status["trace_jsonl"])
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert "run_created" in {event["type"] for event in events}
    assert any(event["type"] == "tool_use" and event["name"] == "proteinclaw_run_status" for event in events)


def test_domain_tools_require_run_id_in_schema(tmp_path: Path) -> None:
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    specs = {spec.name: spec for spec in _build_specs(manager)}
    schema = specs["mcp__proteinclaw_tools__research_pubmed_search"].parameters

    assert "run_id" in schema["properties"]
    assert "run_id" in schema["required"]


def test_skill_create_and_append_are_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROTEINCLAW_HERMES_SKILLS_DIR", str(tmp_path / "skills"))
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    server = build_server(manager)

    created = json.loads(_call(server, "proteinclaw_skill_create", {
        "skill": "proteinclaw-learned-test",
        "content": "---\nname: proteinclaw-learned-test\ndescription: test\n---\n\n# Test\n",
    }))
    appended = json.loads(_call(server, "proteinclaw_skill_append", {
        "skill": "proteinclaw-learned-test",
        "content": "## Learned (run unit-test)\n- Keep edits scoped.",
    }))
    escaped = json.loads(_call(server, "proteinclaw_skill_create", {
        "skill": "../outside",
        "content": "bad",
    }))

    assert created["skill"] == "proteinclaw-learned-test"
    assert appended["skill"] == "proteinclaw-learned-test"
    assert escaped["error"] == "tool_exception"
    text = (tmp_path / "skills" / "proteinclaw-learned-test" / "SKILL.md").read_text(encoding="utf-8")
    assert "Keep edits scoped" in text

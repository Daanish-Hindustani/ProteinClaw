from __future__ import annotations

import asyncio
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

from mcp.types import CallToolRequest, CallToolRequestParams

from proteinclaw.agent.mcp_server import _build_specs, build_server
from proteinclaw.agent.run_manager import RunManager


ROOT = Path(__file__).resolve().parents[2]


def _call(server, name: str, arguments: dict) -> str:
    handler = server.request_handlers[CallToolRequest]
    result = asyncio.run(
        handler(CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments)))
    )
    return result.root.content[0].text


def test_mcp_module_entrypoint_handles_initialize(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update({
        "PROTEINCLAW_RUNS_DIR": str(tmp_path / "runs"),
        "PROTEINCLAW_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        "PROTEINCLAW_SKIP_DEBUG_TOOLS": "1",
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "proteinclaw.agent.mcp_server"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.1.0"},
            },
        }
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()

        selector = selectors.DefaultSelector()
        try:
            selector.register(proc.stdout, selectors.EVENT_READ)
            events = selector.select(timeout=5)
        finally:
            selector.close()
        if not events:
            proc.terminate()
            try:
                _, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr = proc.communicate(timeout=5)
            raise AssertionError(stderr)
        response = json.loads(proc.stdout.readline())

        assert response["id"] == 0
        assert response["result"]["serverInfo"]["name"] == "proteinclaw"
        assert "tools" in response["result"]["capabilities"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


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
    assert "proteinclaw_skill_write" in names
    assert "proteinclaw_skill_patch" in names
    assert "proteinclaw_skill_delete" in names
    assert "proteinclaw_research_record" in names
    assert "proteinclaw_debate_record" in names
    assert "proteinclaw_report_generate" in names
    assert "proteinclaw_data_pdb_analyze" in names
    assert "proteinclaw_design_rfdiffusion3" in names
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
    schema = specs["proteinclaw_research_pubmed_search"].parameters

    assert "run_id" in schema["properties"]
    assert "run_id" in schema["required"]


def test_skill_create_and_append_are_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROTEINCLAW_SKILLS_DIR", str(tmp_path / "skills"))
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


def test_skill_write_patch_and_delete_are_validated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROTEINCLAW_SKILLS_DIR", str(tmp_path / "skills"))
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    server = build_server(manager)

    initial = "---\nname: proteinclaw-learned-test\ndescription: test skill\n---\n\n# Old Title\n"
    updated = "---\nname: proteinclaw-learned-test\ndescription: better test skill\n---\n\n# New Title\n"
    written = json.loads(_call(server, "proteinclaw_skill_write", {
        "skill": "proteinclaw-learned-test",
        "content": initial,
    }))
    patched = json.loads(_call(server, "proteinclaw_skill_patch", {
        "skill": "proteinclaw-learned-test",
        "old": "Old Title",
        "new": "Patched Title",
    }))
    overwritten = json.loads(_call(server, "proteinclaw_skill_write", {
        "skill": "proteinclaw-learned-test",
        "content": updated,
    }))
    invalid = json.loads(_call(server, "proteinclaw_skill_write", {
        "skill": "proteinclaw-learned-test",
        "content": "---\nname: wrong\ndescription: bad\n---\n\n# Bad\n",
    }))
    deleted = json.loads(_call(server, "proteinclaw_skill_delete", {
        "skill": "proteinclaw-learned-test",
    }))
    missing = json.loads(_call(server, "proteinclaw_skill_read", {
        "skill": "proteinclaw-learned-test",
    }))

    skill_file = tmp_path / "skills" / "proteinclaw-learned-test" / "SKILL.md"
    assert written["created"] is True
    assert patched["replacements"] == 1
    assert overwritten["created"] is False
    assert invalid["error"] == "tool_exception"
    assert deleted["skill"] == "proteinclaw-learned-test"
    assert missing["error"] == "tool_exception"
    assert not skill_file.exists()


def test_skill_patch_rejects_ambiguous_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROTEINCLAW_SKILLS_DIR", str(tmp_path / "skills"))
    manager = RunManager(runs_dir=tmp_path / "runs", workspace_root=tmp_path / "workspace")
    server = build_server(manager)

    json.loads(_call(server, "proteinclaw_skill_write", {
        "skill": "proteinclaw-learned-test",
        "content": "---\nname: proteinclaw-learned-test\ndescription: test skill\n---\n\nsame\nsame\n",
    }))
    ambiguous = json.loads(_call(server, "proteinclaw_skill_patch", {
        "skill": "proteinclaw-learned-test",
        "old": "same",
        "new": "different",
    }))
    replace_all = json.loads(_call(server, "proteinclaw_skill_patch", {
        "skill": "proteinclaw-learned-test",
        "old": "same",
        "new": "different",
        "replace_all": True,
    }))

    assert ambiguous["error"] == "ambiguous_patch"
    assert ambiguous["matches"] == 2
    assert replace_all["replacements"] == 2

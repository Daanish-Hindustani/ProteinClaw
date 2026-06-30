# Architecture

ProteinClaw is plugin-first. It does not run an embedded agent loop and it does
not provide a user-facing CLI. External agents own reasoning and orchestration;
ProteinClaw owns scientific MCP tools and reproducible artifacts.

```text
Codex / Claude Code / MCP-capable agent
  planning, web, files, subagents, terminal
        |
        v
ProteinClaw MCP server
  python -m proteinclaw.agent.mcp_server
        |
        +-- run_manager.py: run directories, workspace paths, status
        +-- mcp_tools.py: neutral ToolSpec wrappers for domain tools
        +-- trace.py/report_context.py/triage.py/report.py: traces and reports
        +-- tools/: scientific wrappers and data/research helpers
        +-- runner/: local Docker execution and routing
        +-- skills/: plugin skill read/append/create support
```

## MCP Surface

The server exposes:

- Run lifecycle: `proteinclaw_run_create`, `proteinclaw_run_status`,
  `proteinclaw_run_list`, `proteinclaw_run_resume`,
  `proteinclaw_run_finalize`.
- Domain tools: `proteinclaw_<category>_<tool>`, such as
  `proteinclaw_data_pdb_analyze` and `proteinclaw_design_rfdiffusion3`.
- Artifact tools: `proteinclaw_artifact_read`,
  `proteinclaw_artifact_write`, `proteinclaw_artifact_search`.
- Workflow recorders: `proteinclaw_research_record` and
  `proteinclaw_debate_record` for evidence gathered by native agent tools.
- Skill tools: `proteinclaw_skill_list`, `proteinclaw_skill_read`,
  `proteinclaw_skill_create`, `proteinclaw_skill_write`,
  `proteinclaw_skill_patch`, `proteinclaw_skill_delete`, plus legacy
  `proteinclaw_skill_append`.
- Reporting: `proteinclaw_report_generate`.

ProteinClaw intentionally does not expose generic browser, shell, or subagent
tools. The host agent already has those capabilities.

## GPU Execution

GPU model wrappers run in Docker containers via `runner/local.py`. A run's
workspace is mounted at `/workspace`, and tool wrappers translate host paths
under the run workspace to container paths before execution. Containers are
labeled with `proteinclaw.session=<session_id>` for operator cleanup.

The required host stack is:

- NVIDIA driver and utilities (`nvidia-smi`)
- Docker Engine
- NVIDIA Container Toolkit

Setup and verification live in `docs/gpu-docker-setup.md`.

## Persistence

Runs are directory-based, not SQLite-backed. `RunManager` stores run metadata in
each run directory alongside `plan.md`, `trace.jsonl`, generated artifacts,
`result.json`, and `report.html`.

## Removed Surfaces

The migration removed:

- Embedded orchestration and agent harness modules.
- Legacy embedded-agent registry adapters, skill seeding, and environment handling.
- The `proteinclaw` CLI, setup, doctor, run history, show, cancel, and SQLite
  run database surfaces.
- Duplicate `codex-skills/` packaging.

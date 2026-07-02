# Codex Plugin Installation

This document covers the ProteinClaw Codex plugin surface. It is intentionally
about the plugin contract, not model-provider setup.

## What The Plugin Exposes

ProteinClaw is packaged through `.codex-plugin/plugin.json`.

The manifest points Codex at:

- `./skills/` - workflow, tool, and learned skills.
- `./.mcp.json` - MCP server launch configuration.

The MCP server command is:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

Codex should load the plugin skills, start the MCP server over stdio, and expose
the `proteinclaw_*` tools in the conversation.

## Local Development Setup

From the repository root:

```bash
uv sync --extra dev
uv run --extra dev pytest -m "not gpu and not live"
```

Start the MCP server manually when debugging tool registration:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

The server speaks MCP over stdio, so manual terminal execution will appear to
wait for protocol messages. That is normal. Use Codex or an MCP inspector to
exercise tools interactively.

## Plugin Validation

Validate the plugin package after changing `.codex-plugin/plugin.json`,
`.mcp.json`, `skills/`, or public docs:

```bash
uv run python "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" .
```

Run the repository tests that protect the plugin contract:

```bash
uv run --extra dev pytest tests/test_agent_platform_packaging.py tests/agent/test_skill_invariants.py tests/agent/test_skills.py
```

After changing skills or manifest metadata, reinstall/reload the plugin in
Codex and start a fresh thread. Existing threads may have cached old tool and
skill descriptions.

## Runtime Environment

Useful environment variables:

- `PROTEINCLAW_RUNS_DIR`: run artifact root. Defaults to `./runs` relative to
  the MCP server working directory.
- `PROTEINCLAW_WORKSPACE_ROOT`: host workspace root used by GPU container path
  translation.
- `PROTEINCLAW_SKILLS_DIR`: override skill root for tests or local development.
- `PROTEINCLAW_SKIP_DEBUG_TOOLS`: defaults to hiding debug tools. Set `0` to
  expose them.
- `PROTEINCLAW_TRACE_JSONL`: optional fallback trace file when no run context is
  active.

For installed plugin deployments, prefer an absolute run directory:

```bash
export PROTEINCLAW_RUNS_DIR="$HOME/.proteinclaw/runs"
```

## Expected Agent Behavior

Codex should:

1. Read `proteinclaw-workflow`.
2. Select `proteinclaw-minibinder`, `proteinclaw-nanobody`, or report-only mode.
3. Create or resume a run with `proteinclaw_run_create` or
   `proteinclaw_run_resume`.
4. Use native web/search and subagents for research and critique.
5. Record those native outputs with `proteinclaw_research_record` and
   `proteinclaw_debate_record`.
6. Use ProteinClaw MCP tools for target data, design, structure prediction,
   metrics, artifacts, skill evolution, and reporting.
7. Generate `report.html` with `proteinclaw_report_generate`.

ProteinClaw does not expose generic browsing, generic terminal, or generic
subagent tools. Those remain Codex responsibilities.


# Agent Platform Install

ProteinClaw is consumed as an MCP/plugin package by Codex, Claude Code, or any
MCP-capable agent.

## MCP Launch

Use the repository `.mcp.json` or configure the equivalent server manually:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

```json
{
  "mcpServers": {
    "proteinclaw": {
      "command": "uv",
      "args": ["run", "--project", ".", "python", "-m", "proteinclaw.agent.mcp_server"],
      "env": {
        "PROTEINCLAW_RUNS_DIR": "./runs",
        "PROTEINCLAW_WORKSPACE_ROOT": "~/.proteinclaw/gpu-workspace",
        "PROTEINCLAW_SKIP_DEBUG_TOOLS": "1"
      }
    }
  }
}
```

## Agent Responsibilities

The host agent should use its native web/search, file, shell, and subagent tools
for planning and research. ProteinClaw MCP tools should be used for scientific
pipeline actions, run artifacts, durable skill notes, and reports.

Record externally gathered evidence with:

- `proteinclaw_research_record`
- `proteinclaw_debate_record`

Then generate the final report with `proteinclaw_report_generate`.

## Plugin Skills

Canonical skills are packaged from top-level `skills/`:

- `proteinclaw-workflow`
- `proteinclaw-minibinder`
- `proteinclaw-nanobody`

These skills reference the `proteinclaw_<category>_<tool>` MCP names and assume
the external agent owns orchestration.

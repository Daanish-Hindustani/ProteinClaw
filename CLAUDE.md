# ProteinClaw Agent Notes

ProteinClaw is now an MCP/plugin package. Use the host agent's native planning,
web, file, terminal, and subagent capabilities, and call ProteinClaw only for
scientific tools, run artifacts, skill notes, traces, and reports.

Start the MCP server with:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

Current architecture and setup docs:

- `README.md`
- `ARCHITECTURE.md`
- `SETUP.md`
- `docs/agent-platform-install.md`
- `docs/gpu-docker-setup.md`
- `docs/plugin-migration-removal-audit.md`

# ProteinClaw Agent Notes

For this repository, treat `.codex-plugin/plugin.json`, `.mcp.json`, `skills/`,
and `docs/ARCHITECTURE.md` as the public plugin contract.

Start the MCP server with:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

Run default tests with:

```bash
uv run --extra dev pytest -m "not gpu and not live"
```

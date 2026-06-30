# Plan

The original CLI-first development plan is superseded. ProteinClaw is now a
plugin-first MCP package:

- External agents own planning, research, subagents, and orchestration.
- ProteinClaw owns MCP tools, GPU Docker wrappers, artifacts, traces, skills,
  triage, and reports.
- The runtime entrypoint is `python -m proteinclaw.agent.mcp_server`.

See `docs/plugin-migration-removal-audit.md` for the migration inventory.

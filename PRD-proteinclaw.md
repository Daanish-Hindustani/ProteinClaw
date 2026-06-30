# ProteinClaw PRD

The original CLI/autonomous-agent PRD is superseded by the plugin-first design.

Current product definition:

- ProteinClaw is a scientific MCP/plugin layer.
- Codex, Claude Code, or another MCP-capable host agent owns planning,
  research, subagents, and orchestration.
- ProteinClaw exposes domain tools, run lifecycle, artifacts, skill updates,
  trace capture, triage, report generation, and GPU Docker execution.
- There is no user-facing CLI and no embedded agent harness.

Current implementation references:

- `README.md`
- `ARCHITECTURE.md`
- `SETUP.md`
- `docs/agent-platform-install.md`
- `docs/plugin-migration-removal-audit.md`
- `docs/gpu-docker-setup.md`

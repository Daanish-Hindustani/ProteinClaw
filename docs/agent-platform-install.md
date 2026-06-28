# Agent Platform Install

ProteinClaw is designed to run natively from Codex or Claude Code. The platform
owns the model loop, web research, and subagent/task orchestration. ProteinClaw
provides MCP tools and workflow skills for scientific execution.

## Codex

Install this repository as a Codex plugin. The repo includes:

- `.codex-plugin/plugin.json` — Codex plugin metadata.
- `.mcp.json` — MCP server config for `proteinclaw`.
- `skills/proteinclaw-workflow/SKILL.md` — Codex-facing workflow skill.
- `skills/proteinclaw-minibinder/SKILL.md` — de-novo minibinder entry skill.
- `skills/proteinclaw-nanobody/SKILL.md` — VHH/nanobody entry skill.

The bundled MCP config launches:

```bash
uv run --project . proteinclaw mcp serve
```

That means the plugin can run from the checked-out repository as long as `uv`,
Docker, NVIDIA drivers, and NVIDIA Container Toolkit are installed.

After installation, ask Codex for a protein-design goal in plain language. Codex
should load the ProteinClaw workflow skill, use native web/subagents for
research and debate, create a ProteinClaw run, record those native steps with
`proteinclaw_research_record` and `proteinclaw_debate_record`, execute MCP
tools, iterate against the quality gate, and return `runs/<run_id>/report.html`.

## Claude Code

Claude Code does not use Codex plugin metadata. Add the same MCP server to
Claude Code:

```json
{
  "mcpServers": {
    "proteinclaw": {
      "command": "uv",
      "args": ["run", "--project", ".", "proteinclaw", "mcp", "serve"],
      "env": {
        "PROTEINCLAW_RUNS_DIR": "./runs",
        "PROTEINCLAW_WORKSPACE_ROOT": "~/.proteinclaw/gpu-workspace",
        "PROTEINCLAW_SKIP_DEBUG_TOOLS": "1"
      }
    }
  }
}
```

Then prompt Claude Code to use the ProteinClaw workflow:

```text
Use ProteinClaw to design a minibinder for <target>. Use native web research
and debate, then ProteinClaw MCP tools for the scientific pipeline. Return the
final report.html and ranked designs.
```

Claude should read the canonical ProteinClaw skills through
`proteinclaw_skill_read`, record native web/subagent work with
`proteinclaw_research_record` and `proteinclaw_debate_record`, and follow the
same run loop as Codex.

## Boundary

ProteinClaw MCP intentionally does not expose generic web search or generic
subagent tools. Codex and Claude Code should use their own native capabilities
for those tasks.

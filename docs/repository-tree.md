# Repository Tree

This is the high-level layout for the Codex plugin migration.

```text
.
├── .codex-plugin/
│   └── plugin.json
├── .mcp.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── agent-platform-install.md
│   ├── gpu-docker-setup.md
│   ├── mcp-tool-surface.md
│   ├── plugin-migration-removal-audit.md
│   └── repository-tree.md
├── skills/
│   ├── proteinclaw-workflow/
│   ├── proteinclaw-minibinder/
│   ├── proteinclaw-nanobody/
│   ├── proteinclaw-tool-*/
│   └── proteinclaw-learned-*/
├── src/proteinclaw/
│   ├── agent/
│   ├── runner/
│   ├── tools/
│   └── report.py
├── tests/
└── pyproject.toml
```

## Public Plugin Contract

Treat these as the public contract:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/`
- `docs/ARCHITECTURE.md`

Changes to those files should be tested with plugin packaging tests and, when
available, plugin validation.

## Skills

Top-level `skills/` is what Codex loads.

- `proteinclaw-workflow`: high-level operating model for Codex plus
  ProteinClaw MCP.
- `proteinclaw-minibinder`: detailed de-novo minibinder workflow.
- `proteinclaw-nanobody`: detailed VHH/nanobody workflow.
- `proteinclaw-tool-*`: per-tool operational guidance.
- `proteinclaw-learned-*`: durable lessons that should influence future runs.

All `SKILL.md` files require YAML frontmatter with matching `name:` and a
non-empty `description:`.

## Agent Layer

`src/proteinclaw/agent/` contains the plugin-facing agent support code:

- `mcp_server.py`: stdio MCP server and tool wrappers.
- `mcp_tools.py`: tool-name translation and path translation helpers.
- `run_manager.py`: run directory lifecycle and context payloads.
- `report_context.py`: trace/report context extraction.
- `skills.py`: packaged skill loader and skill-root helpers.
- `trace.py`, `triage.py`: trace and result processing.

ProteinClaw does not host a generic autonomous planning loop in this branch.
Codex provides that behavior.

## Scientific Tool Layer

`src/proteinclaw/tools/` contains domain tools and tool registry definitions.
Tools own their JSON schemas and implementation metadata. The MCP server wraps
registered tools into `proteinclaw_<category>_<tool>` names.

Container-backed tools use manifests and the runner layer. In-process tools
such as PDB analysis and interface metrics run directly in Python.

## Runner Layer

`src/proteinclaw/runner/` decides how a tool executes. It handles local/container
dispatch and workspace path translation.

## Runtime Artifacts

Runs are generated artifacts under `PROTEINCLAW_RUNS_DIR` or `./runs` by
default. A run may contain:

- `run.json`
- `plan.md`
- `trace.jsonl`
- `research.jsonl`
- `debate.jsonl`
- `result.json`
- `report.html`
- `designs/`
- `scratch/`

Generated run directories should not be committed unless a tiny file is
intentionally promoted into `tests/fixtures/`.

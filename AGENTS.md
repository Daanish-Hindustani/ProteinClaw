# ProteinClaw Agent Notes

Act like a pragmatic senior engineer. Ship the simplest correct solution, keep
changes scoped, and do not over-engineer abstractions.

## Public Contract

Treat these files as the public plugin contract:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/`
- `docs/ARCHITECTURE.md`

When any of those change, update the relevant docs and run the plugin/skill
tests. The plugin is Codex-first: Codex owns planning, browsing, shell work,
and subagents; ProteinClaw owns MCP domain tools, run artifacts, scoped skills,
and reports.

## Docs To Read Before Editing

- `README.md` - repo entry point and common commands.
- `docs/ARCHITECTURE.md` - runtime model and responsibility split.
- `docs/mcp-tool-surface.md` - MCP tool families and boundaries.
- `docs/agent-platform-install.md` - plugin install/reload workflow.
- `docs/gpu-docker-setup.md` - GPU/container assumptions and OOM handling.
- `docs/repository-tree.md` - ownership map and runtime artifacts.
- `docs/plugin-migration-removal-audit.md` - what was kept or removed in the
  plugin migration.

When changing agent behavior, update the relevant `skills/proteinclaw-*`
`SKILL.md` file. The high-level operating playbook is
`skills/proteinclaw-workflow/SKILL.md`.

## Code Quality

Use Ruff and pytest as the default local gate:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest -m "not gpu and not live"
```

Before opening a PR or after changing plugin metadata/skills, also run:

```bash
uv run --extra dev pytest tests/test_agent_platform_packaging.py tests/agent/test_skill_invariants.py tests/agent/test_skills.py
uv run python .github/scripts/validate_codex_plugin.py .
```

Keep Ruff fixes narrow. Do not introduce broad formatting churn unless the user
asked for it.

## MCP Server

Start the MCP server with:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

The server speaks MCP over stdio, so a manual terminal run may appear to wait
for protocol input. That is expected.

Domain tools use `proteinclaw_<category>_<tool>` names. Every scientific run
must start with `proteinclaw_run_create` or `proteinclaw_run_resume`, then pass
`run_id` through subsequent tools.

## Skills And Agent Behavior

Skill files are production guidance for future agents, not scratch notes.

- Keep `SKILL.md` frontmatter valid with matching `name:` and a non-empty
  `description:`.
- Prefer precise edits over appending long logs.
- Put durable lessons in focused `proteinclaw-learned-*` skills.
- Put run-specific facts in the run `plan.md`, not global skills.
- Do not reintroduce old embedded-agent/Hermes assumptions. Native Codex
  research/debate is recorded through `proteinclaw_research_record` and
  `proteinclaw_debate_record`.

## Runtime Artifacts

Generated runs are local runtime artifacts. Do not commit `runs/`, generated
PDBs, reports, logs, caches, or GPU workspaces unless a tiny artifact is
explicitly promoted into `tests/fixtures/`.

Important environment variables:

- `PROTEINCLAW_RUNS_DIR`
- `PROTEINCLAW_WORKSPACE_ROOT`
- `PROTEINCLAW_SKILLS_DIR`
- `PROTEINCLAW_SKIP_DEBUG_TOOLS`

## Scientific Boundaries

ProteinClaw outputs are computational candidates. Do not present generated
sequences, structures, scores, or reports as experimentally validated binders.
Be explicit about failed tools, skipped confirmations, OOMs, weak target
resolution, and whether the strict quality gate was actually met.

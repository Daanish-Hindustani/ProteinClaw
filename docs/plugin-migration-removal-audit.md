# Plugin Migration Removal Audit

Status labels:

- `keep`: remains part of the plugin/MCP package.
- `remove`: removed from source because it belonged to embedded orchestration,
  the CLI product, duplicate packaging, or historical artifacts.
- `refactor`: retained after renaming or narrowing responsibilities.

## Package Metadata

| Surface | Status | Rationale |
| --- | --- | --- |
| `pyproject.toml` | refactor | Removed console script and embedded-agent dependency; package is MCP/plugin-first. |
| `.mcp.json` | refactor | Launches `python -m proteinclaw.agent.mcp_server`. |
| `.codex-plugin/plugin.json` | keep | Plugin metadata remains canonical. |

## Source

| Surface | Status | Rationale |
| --- | --- | --- |
| `src/proteinclaw/agent/mcp_server.py` | keep | Primary runtime interface. |
| `src/proteinclaw/agent/mcp_tools.py` | refactor | Neutral `ToolSpec` and `proteinclaw_<category>_<tool>` names. |
| `src/proteinclaw/agent/run_manager.py` | keep | Directory-based run lifecycle. |
| `src/proteinclaw/agent/trace.py` | keep | Trace writer support. |
| `src/proteinclaw/agent/triage.py` | keep | Result extraction and ranking. |
| `src/proteinclaw/agent/report_context.py` | keep | Report trace context moved out of removed agent core. |
| `src/proteinclaw/agent/skills.py` | refactor | Plugin skill helpers; no external agent skill store. |
| `src/proteinclaw/agent/core.py` | remove | Embedded agent orchestration. |
| `src/proteinclaw/agent/*harness.py` | remove | Legacy embedded agent harness. |
| `src/proteinclaw/agent/*builtins.py` | remove | Embedded built-in tools for old harness. |
| `src/proteinclaw/agent/codex_mcp.py` | remove | Per-run Codex config bridge from old harness. |
| `src/proteinclaw/cli.py` | remove | CLI product surface removed. |
| `src/proteinclaw/setup.py` | remove | CLI setup flow removed. |
| `src/proteinclaw/doctor.py` | remove | Environment checks are docs/tests, not CLI. |
| `src/proteinclaw/db.py` | remove | SQLite run history removed. |
| `src/proteinclaw/tools/` | keep | Scientific/domain wrappers. |
| `src/proteinclaw/runner/` | keep | Docker/local routing runtime. |
| `src/proteinclaw/report.py` | keep | HTML report generation. |
| `src/proteinclaw/analysis.py` | keep | Interface metrics implementation. |

## Skills and Artifacts

| Surface | Status | Rationale |
| --- | --- | --- |
| `skills/` | keep | Canonical plugin skills. |
| `codex-skills/` | remove | Duplicate skill packaging. |
| `src/proteinclaw/skills/` | remove | Consolidated into top-level plugin `skills/`. |
| `runs/` | remove from package contract | Historical outputs only; keep only explicit fixtures if needed. |
| `runs_external_mor.log` | remove from package contract | Historical run log, not runtime source. |

## Tests

| Surface | Status | Rationale |
| --- | --- | --- |
| MCP server/tool-spec tests | refactor | Assert module launch, neutral specs, and new tool names. |
| Run manager, trace, triage, report tests | keep | Core plugin behavior. |
| Tool registry, router, local runner tests | keep | Scientific runtime behavior. |
| Scientific wrapper tests | keep | Domain behavior. |
| CLI/setup/doctor/db tests | remove | Removed product surfaces. |
| Embedded harness/agent loop tests | remove | Removed embedded orchestration. |

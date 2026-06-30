# ProteinClaw

ProteinClaw is a Codex plugin for protein binder design workflows. It packages
domain-specific MCP tools and Codex skills for target retrieval, binder
generation, structure prediction, interface metrics, run artifacts, and report
generation.

Codex owns planning, web research, file inspection, terminal work, and
subagents. ProteinClaw owns the scientific workflow tools and durable run
artifacts.

## Status

ProteinClaw is pre-1.0 research software. Outputs are computational design
candidates, not validated therapeutics or diagnostics. Use appropriate
scientific review, wet-lab validation, and safety review before acting on any
design.

## Requirements

- Python 3.11 or 3.12
- `uv`
- Codex with plugin support
- Docker and NVIDIA Container Toolkit for GPU-backed tools

GPU tools are optional for local packaging tests, but required for RFdiffusion3,
ProteinMPNN, ESMFold, and AlphaFold2-multimer workflows.

## Codex Plugin

The Codex plugin manifest is `.codex-plugin/plugin.json`. It points Codex at:

- `./skills/` for workflow and tool skills
- `./.mcp.json` for the ProteinClaw MCP server

The primary agent playbook is `skills/proteinclaw-workflow/SKILL.md`. It tells
Codex how to choose minibinder vs nanobody workflows, create runs, record native
research/debate, write run artifacts, execute the MCP pipeline, update scoped
skills, and generate reports.

The MCP server launches with:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

For local development, install dependencies and run the default test suite:

```bash
uv sync --extra dev
uv run --extra dev ruff check .
uv run --extra dev pytest -m "not gpu and not live"
```

Validate the Codex plugin package:

```bash
uv run python /Users/daanishhindustano/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

After changing plugin metadata or skills, reinstall the plugin in Codex and
start a fresh thread so Codex reloads the updated tool and skill surface.

Detailed plugin installation and reload notes are in
`docs/agent-platform-install.md`.

## MCP Tool Surface

Domain tools use the `proteinclaw_<category>_<tool>` naming convention. Common
tools include:

- `proteinclaw_run_create`
- `proteinclaw_data_pdb_fetch`
- `proteinclaw_data_uniprot_fetch`
- `proteinclaw_research_literature_search`
- `proteinclaw_design_rfdiffusion3`
- `proteinclaw_design_proteinmpnn`
- `proteinclaw_structure_esmfold`
- `proteinclaw_structure_alphafold2_multimer`
- `proteinclaw_analysis_interface_metrics`
- `proteinclaw_analysis_afm_screen_score`
- `proteinclaw_research_record`
- `proteinclaw_debate_record`
- `proteinclaw_artifact_read`
- `proteinclaw_artifact_write`
- `proteinclaw_report_generate`

Run artifacts are written under `PROTEINCLAW_RUNS_DIR`, or `./runs` by default.
Generated runs are local runtime artifacts and are not part of the repository
contract.

See `docs/mcp-tool-surface.md` for the full tool-family contract.

## GPU Setup

Install Docker Engine, NVIDIA drivers, and the NVIDIA Container Toolkit. Verify
GPU container access with:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Useful runtime environment variables:

- `PROTEINCLAW_RUNS_DIR`: run artifact directory, default `./runs`
- `PROTEINCLAW_WORKSPACE_ROOT`: host workspace root for GPU container mounts
- `PROTEINCLAW_SKIP_DEBUG_TOOLS`: set to `0` to expose debug tools
- `PROTEINCLAW_SKILLS_DIR`: override plugin skill root for tests

See `docs/gpu-docker-setup.md` for runtime path, compute-budget, and OOM
handling guidance.

## Development

See `CONTRIBUTING.md` for development workflow, test policy, and pull request
expectations.

Useful docs:

- `docs/ARCHITECTURE.md` - runtime architecture and responsibility split.
- `docs/agent-platform-install.md` - Codex plugin install/reload workflow.
- `docs/mcp-tool-surface.md` - MCP tool families and boundaries.
- `docs/gpu-docker-setup.md` - Docker/GPU setup and failure handling.
- `docs/repository-tree.md` - repository layout and public contract.
- `docs/plugin-migration-removal-audit.md` - what was kept, refactored, or
  removed during the plugin migration.

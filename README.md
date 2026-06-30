# ProteinClaw

ProteinClaw is a scientific MCP/plugin layer for protein binder design. Codex,
Claude Code, or another MCP-capable agent owns planning, web research,
subagents, file inspection, and orchestration. ProteinClaw exposes the domain
tools, GPU Docker execution, run artifacts, traces, skills, triage, and report
generation.

There is no `proteinclaw` CLI. Start the MCP server as a Python module:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

The packaged plugin points MCP clients at `.mcp.json`, which launches the same
module entrypoint.

## Runtime Model

```text
External agent
  -> ProteinClaw MCP server
    -> run lifecycle and artifacts
    -> PDB/UniProt/RCSB/literature tools
    -> RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer Docker wrappers
    -> interface metrics, triage, trace, report generation
```

The agent should create or resume a run first with `proteinclaw_run_create` or
`proteinclaw_run_resume`, then pass `run_id` into data, design, structure,
analysis, artifact, skill, and report tools. Generic web search, shell access,
and subagents are intentionally not re-exposed by ProteinClaw.

## Install

```bash
uv sync --extra dev
uv run --extra dev pytest -m "not gpu and not live"
```

For GPU tools, install Docker Engine and the NVIDIA Container Toolkit, then
verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

See `docs/gpu-docker-setup.md` for the Ubuntu setup recipe.

## Tool Names

Domain tools use the `proteinclaw_<category>_<tool>` form, for example:

- `proteinclaw_data_pdb_analyze`
- `proteinclaw_design_rfdiffusion3`
- `proteinclaw_design_proteinmpnn`
- `proteinclaw_structure_esmfold`
- `proteinclaw_structure_alphafold2_multimer`
- `proteinclaw_analysis_interface_metrics`

Run and support tools include `proteinclaw_run_create`,
`proteinclaw_artifact_read`, `proteinclaw_research_record`,
`proteinclaw_debate_record`, `proteinclaw_skill_write`,
`proteinclaw_skill_patch`, `proteinclaw_skill_delete`, and
`proteinclaw_report_generate`.

## Skills

Canonical plugin skills live under `skills/`. The duplicate `codex-skills/`
tree has been removed. The MCP skill tools read, create, write/replace, patch, and delete within the
plugin skill namespace, with `PROTEINCLAW_SKILLS_DIR` available as a test/local
override. `proteinclaw_skill_append` remains available for compatibility, but
new self-evolution should prefer clean `write`/`patch`/`delete` operations over
append-only logs.

## Artifacts

Runs are directory-based under `PROTEINCLAW_RUNS_DIR` or `./runs` by default.
Each run contains `plan.md`, `trace.jsonl`, `result.json`, `report.html`, and
tool outputs. Historical generated runs are not part of the package contract and
should be kept only when they are explicit fixtures.

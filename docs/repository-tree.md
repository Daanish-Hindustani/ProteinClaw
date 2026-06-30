# Repository Tree

ProteinClaw is now organized as a plugin-first MCP package. The important path
to follow is:

```text
external agent -> .mcp.json -> proteinclaw.agent.mcp_server -> tools/runner/reporting
```

## File Guide

- `.codex-plugin/plugin.json`: Codex plugin metadata. Points at top-level
  `skills/` and `.mcp.json`.
- `.mcp.json`: MCP server launch config. Runs
  `python -m proteinclaw.agent.mcp_server`.
- `skills/`: canonical plugin skills loaded by Codex/plugin hosts.
- `src/proteinclaw/agent/`: MCP server, neutral tool specs, run lifecycle,
  trace/report context, triage, and plugin skill helpers.
- `src/proteinclaw/tools/`: domain tools exposed through MCP.
- `src/proteinclaw/runner/`: Docker/local execution and routing.
- `tests/`: non-GPU unit tests plus GPU-marked wrapper tests under
  `tests/tools/**/test_e2e_gpu.py`.
- `docs/gpu-docker-setup.md`: host setup recipe for NVIDIA driver, Docker, and
  NVIDIA Container Toolkit.
- `docs/plugin-migration-removal-audit.md`: what was kept, removed, or
  refactored in the plugin migration.

Generated run outputs live under `runs/` and are intentionally omitted from this
tree.

## Tree

```text
ProteinClaw/
├── .codex-plugin/
│   └── plugin.json
├── .mcp.json
├── ARCHITECTURE.md
├── CLAUDE.md
├── HANDOFF.md
├── LICENSE
├── NOTES.md
├── PLAN.md
├── PRD-proteinclaw.md
├── README.md
├── SETUP.md
├── banner.png
├── data/
│   └── natural_vhh_repertoire.fasta
├── docs/
│   ├── agent-platform-install.md
│   ├── gpu-docker-setup.md
│   ├── plugin-migration-removal-audit.md
│   └── repository-tree.md
├── pyproject.toml
├── runs_external_mor.log
├── scripts/
│   └── harvest_vhh_repertoire.py
├── skills/
│   ├── proteinclaw-learned-ig-v-flat-face/
│   │   └── SKILL.md
│   ├── proteinclaw-learned-target-resolution/
│   │   └── SKILL.md
│   ├── proteinclaw-minibinder/
│   │   └── SKILL.md
│   ├── proteinclaw-nanobody/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-alphafold2-multimer/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-esmfold/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-interface-metrics/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-nanobody-library/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-proteinmpnn/
│   │   └── SKILL.md
│   ├── proteinclaw-tool-rfdiffusion3/
│   │   └── SKILL.md
│   └── proteinclaw-workflow/
│       └── SKILL.md
├── src/
│   └── proteinclaw/
│       ├── __init__.py
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── mcp_server.py
│       │   ├── mcp_tools.py
│       │   ├── report_context.py
│       │   ├── run_manager.py
│       │   ├── skills.py
│       │   ├── trace.py
│       │   └── triage.py
│       ├── analysis.py
│       ├── report.py
│       ├── runner/
│       │   ├── __init__.py
│       │   ├── local.py
│       │   └── router.py
│       └── tools/
│           ├── __init__.py
│           ├── _container_tools.py
│           ├── _gpu_metrics.py
│           ├── _http.py
│           ├── _paths.py
│           ├── _smoke/
│           │   ├── Dockerfile
│           │   ├── implementation.py
│           │   ├── tool.yaml
│           │   └── tool_entrypoint.py
│           ├── alphafold2_multimer/
│           │   ├── Dockerfile
│           │   ├── _normalize.py
│           │   ├── implementation.py
│           │   ├── tool.yaml
│           │   └── tool_entrypoint.py
│           ├── binding_affinity.py
│           ├── esmfold/
│           │   ├── Dockerfile
│           │   ├── _normalize.py
│           │   ├── implementation.py
│           │   ├── tool.yaml
│           │   └── tool_entrypoint.py
│           ├── interface_metrics.py
│           ├── literature.py
│           ├── nanobody_library.py
│           ├── pdb.py
│           ├── proteinmpnn/
│           │   ├── Dockerfile
│           │   ├── _normalize.py
│           │   ├── implementation.py
│           │   ├── tool.yaml
│           │   └── tool_entrypoint.py
│           ├── pubmed.py
│           ├── rcsb.py
│           ├── rfdiffusion3/
│           │   ├── Dockerfile
│           │   ├── _normalize.py
│           │   ├── implementation.py
│           │   ├── tool.yaml
│           │   └── tool_entrypoint.py
│           └── uniprot.py
├── tests/
│   ├── __init__.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── test_mcp_server.py
│   │   ├── test_mcp_session_wiring.py
│   │   ├── test_mcp_tools.py
│   │   ├── test_run_manager.py
│   │   ├── test_skill_invariants.py
│   │   ├── test_skills.py
│   │   ├── test_trace.py
│   │   └── test_triage.py
│   ├── test_agent_platform_packaging.py
│   ├── test_container_tools.py
│   ├── test_interface_metrics.py
│   ├── test_local_runner.py
│   ├── test_nanobody_metrics.py
│   ├── test_nanobody_workflow.py
│   ├── test_package.py
│   ├── test_registry.py
│   ├── test_report.py
│   ├── test_report_activity.py
│   ├── test_report_round_reasoning.py
│   ├── test_router.py
│   └── tools/
│       ├── __init__.py
│       ├── _smoke/
│       │   ├── __init__.py
│       │   └── test_smoke.py
│       ├── alphafold2_multimer/
│       │   ├── __init__.py
│       │   ├── test_e2e_gpu.py
│       │   ├── test_nanobody_calibration_gpu.py
│       │   └── test_normalize.py
│       ├── esmfold/
│       │   ├── __init__.py
│       │   ├── test_e2e_gpu.py
│       │   └── test_normalize.py
│       ├── proteinmpnn/
│       │   ├── __init__.py
│       │   ├── test_e2e_gpu.py
│       │   ├── test_fasta_parser.py
│       │   └── test_normalize.py
│       ├── rfdiffusion3/
│       │   ├── __init__.py
│       │   ├── test_chain_detection.py
│       │   ├── test_e2e_gpu.py
│       │   └── test_normalize.py
│       ├── test_binding_affinity.py
│       ├── test_literature.py
│       ├── test_nanobody_library.py
│       ├── test_pdb.py
│       ├── test_pubmed.py
│       ├── test_rcsb.py
│       └── test_uniprot.py
└── uv.lock
```

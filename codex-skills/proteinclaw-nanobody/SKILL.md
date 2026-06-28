---
name: proteinclaw-nanobody
description: Run ProteinClaw nanobody/VHH candidate scoring from Codex using native research/debate and ProteinClaw MCP tools.
---

# ProteinClaw Nanobody

Use this skill when the user asks Codex to generate or score VHH/nanobody candidates with ProteinClaw.

## Required Flow

1. Load `proteinclaw-workflow`.
2. Create a run with `proteinclaw_run_create`.
3. Read canonical details with `proteinclaw_skill_read` for `proteinclaw-nanobody`, `proteinclaw-tool-nanobody-library`, `proteinclaw-tool-esmfold`, `proteinclaw-tool-alphafold2-multimer`, and `proteinclaw-tool-interface-metrics`.
4. Use Codex native web/search for target, epitope, and nanobody precedent, then call `proteinclaw_research_record`.
5. Use `mcp__proteinclaw_tools__data_pdb_analyze` on target and complex PDB paths when the main agent or native subagents need chain, epitope, crop, or interface evidence.
6. Use Codex native subagents to critique epitope and library strategy, giving them PDB-analysis summaries instead of raw PDB bytes when possible, then call `proteinclaw_debate_record`.
7. Execute ProteinClaw MCP tools for target setup, nanobody library generation, ESMFold monomer filtering, AF2-multimer scoring, interface metrics, and report generation.
8. Apply the canonical nanobody quality gate. If it is unmet and budget remains, iterate with a changed epitope, library size/diversity, or filtering threshold.
9. Return `report.html`, ranked candidates, trace path, and a concise metric summary.

## Boundaries

- Do not use RFdiffusion3 or ProteinMPNN for the VHH library workflow unless the user explicitly changes workflows.
- Do not use ProteinClaw MCP as a generic browser or subagent runner; Codex provides those natively.
- Record all native research and debate in the run before generating the final report.

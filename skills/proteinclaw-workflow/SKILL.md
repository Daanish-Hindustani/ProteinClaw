---
name: proteinclaw-workflow
description: Run ProteinClaw through native Codex research/debate plus ProteinClaw MCP scientific tools.
---

# ProteinClaw Workflow

Use this skill when the user asks Codex to design, evaluate, or report protein binders with ProteinClaw.

## Operating Model

- Use Codex native web/search and native subagents for literature search, background research, critique, and hypothesis debate.
- Use only the `proteinclaw` MCP server for ProteinClaw-specific scientific execution, artifacts, scoped skill updates, and report generation.
- Do not look for ProteinClaw-provided generic web search or generic subagent tools. They are intentionally not exposed.
- Start every scientific run with `proteinclaw_run_create`, then pass the returned `run_id` to ProteinClaw MCP tools.
- After native web/search, call `proteinclaw_research_record` so the run trace and report contain the evidence and citations.
- After native subagent critique or debate, call `proteinclaw_debate_record` so the run trace and report contain the adjudication.
- Use `mcp__proteinclaw_tools__data_pdb_analyze` when the main agent or a native subagent needs chain, residue, gap, hotspot, confidence, or interface evidence from a PDB path.
- Ask follow-up questions only when target identity, workflow type, design constraints, or safety-critical assumptions are ambiguous.

## Canonical Skill Content

Read the canonical ProteinClaw skill files from the repository or through `proteinclaw_skill_read` before executing a run:

- `proteinclaw-minibinder` for de-novo RFdiffusion3 minibinder workflows.
- `proteinclaw-nanobody` for VHH/nanobody workflows.
- `proteinclaw-tool-*` before each scientific tool family.
- `proteinclaw-learned-*` when target class, fold class, or prior lessons may apply.

## Run Loop

1. Clarify workflow and constraints only if needed.
2. Create a run with `proteinclaw_run_create`.
3. Use native research and subagents to gather evidence and debate hypotheses, then record them with `proteinclaw_research_record` and `proteinclaw_debate_record`.
4. Resolve target context with ProteinClaw data/PDB/UniProt/RCSB tools, including `mcp__proteinclaw_tools__data_pdb_analyze` for structural inspection.
5. Write a concrete design plan and hypotheses into run artifacts.
6. Execute the scientific pipeline through ProteinClaw MCP tools.
7. Score and triage designs with ProteinClaw metrics tools.
8. Append durable, general lessons with `proteinclaw_skill_append` or create scoped new lessons with `proteinclaw_skill_create`.
9. Iterate until the canonical skill quality gate is met or the skill-defined stop condition applies.
10. Generate `report.html` with `proteinclaw_report_generate` and return the report path, ranked designs, trace, and concise summary.

## Tool Boundary

ProteinClaw MCP tools are for domain execution only: run lifecycle, target/PDB/UniProt/RCSB helpers, PubMed/literature helpers, RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, interface metrics, artifact helpers, scoped skill management, and report generation.

Codex is responsible for general browsing, general file inspection outside ProteinClaw artifacts, debate, task decomposition, and subagent orchestration.

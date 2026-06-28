---
name: proteinclaw-minibinder
description: Run ProteinClaw de-novo minibinder design from Codex using native research/debate and ProteinClaw MCP scientific tools.
---

# ProteinClaw Minibinder

Use this skill when the user asks Codex to design a de-novo minibinder, peptide binder, or compact protein binder with ProteinClaw.

## Required Flow

1. Load `proteinclaw-workflow`.
2. Create a run with `proteinclaw_run_create`.
3. Read canonical details with `proteinclaw_skill_read` for `proteinclaw-minibinder` and the tool skills before each stage.
4. Use Codex native web/search for target and method evidence, then call `proteinclaw_research_record` with query, summary, citations, and notes.
5. Use `mcp__proteinclaw_tools__data_pdb_analyze` on target, backbone, or complex PDB paths when the main agent or native subagents need structural evidence.
6. Use Codex native subagents for critique/debate, giving them PDB-analysis summaries instead of raw PDB bytes when possible, then call `proteinclaw_debate_record` with the prompt, competing position, summary, evidence, and decision.
7. Execute ProteinClaw MCP tools in order: target/PDB or UniProt helpers, RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, interface metrics, triage/report generation.
8. Iterate until the canonical quality gate is met or the stop condition is reached.
9. Return `report.html`, ranked designs, trace path, and a concise metric summary.

## Boundaries

- Do not call generic web or generic subagent tools through ProteinClaw MCP. Codex owns those capabilities natively.
- Do not hand-roll scientific pipeline steps that ProteinClaw MCP exposes.
- Keep durable learned lessons inside the ProteinClaw skill namespace with `proteinclaw_skill_append` or `proteinclaw_skill_create`.

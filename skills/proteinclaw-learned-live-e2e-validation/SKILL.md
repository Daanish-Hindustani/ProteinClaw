---
name: proteinclaw-learned-live-e2e-validation
description: ProteinClaw learned guidance for auditing real end-to-end workflow validation.
---

# Learned: Live End-To-End Validation

Use this skill when auditing whether a ProteinClaw campaign actually exercised
the full Codex plugin workflow.

## What A Real E2E Run Must Trace

A valid end-to-end run should show, in `trace.jsonl`, `plan.md`, `result.json`,
and `report.html`:

- The agent read the workflow and relevant tool skills.
- `proteinclaw_run_create` or `proteinclaw_run_resume` established a scoped run.
- Native research was performed and recorded with `proteinclaw_research_record`.
- Native critique/debate was performed and recorded with
  `proteinclaw_debate_record`.
- Target resolution used data tools such as RCSB, UniProt, PDB fetch, and
  `proteinclaw_data_pdb_analyze`.
- The selected scientific branch actually ran:
  - minibinder: RFdiffusion3, ProteinMPNN, ESMFold, AF2-multimer, interface
    metrics;
  - nanobody: nanobody library, ESMFold, AF2-multimer, AF-M confirmation when
    claiming final hits, CDR/interface metrics.
- `proteinclaw_report_generate` created `result.json` and `report.html`.
- Any claimed skill evolution corresponds to an actual `proteinclaw_skill_*`
  tool call.

## Minimal Does Not Mean Production Quality

A smoke-test campaign may use tiny counts to prove wiring:

- one or two backbones,
- a few MPNN sequences,
- a small VHH library,
- one-model AF2 triage,
- a single interface metrics call.

That validates tool-chain integration only. It does not validate binder quality.
The report and final answer must separate "the workflow ran" from "the design
met the strict gate."

## Audit Failure Modes

Flag the run as incomplete when:

- Research or debate happened in prose but was not recorded through the MCP
  recorders.
- The final summary claims a skill update but no skill MCP call appears in the
  trace.
- `report.html` was generated without `result.json` or without ranked design
  metrics.
- AF2-multimer was skipped but the answer still claims binding confidence.
- Nanobody outputs are ranked on ESMFold monomer confidence instead of AF-M
  complex evidence.
- Minibinder outputs are ranked on complex pLDDT alone while ipSAE, ipTM,
  hotspot satisfaction, BSA, or clashes are missing.

## Reporting Language

Use blunt labels:

- `workflow_validated`: the plugin path ran end to end, even if candidate counts
  were tiny.
- `candidate_screened`: designs were generated and scored but did not clear the
  strict gate.
- `strict_gate_passed`: all required metrics exist and pass the workflow gate.
- `needs_human_review`: target resolution, tool failure, or metric gaps prevent
  a defensible design conclusion.


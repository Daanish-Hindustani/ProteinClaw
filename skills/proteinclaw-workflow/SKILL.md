---
name: proteinclaw-workflow
description: Detailed Codex operating workflow for ProteinClaw MCP protein binder design runs.
---

# ProteinClaw Workflow

Use this skill when the user asks Codex to design, evaluate, triage, refine,
or report protein binders with ProteinClaw.

ProteinClaw is not a standalone agent loop. Codex owns planning, browsing,
general file inspection, shell work, and native subagents. ProteinClaw owns the
domain MCP tools, run lifecycle, scientific artifacts, scoped skill updates,
and final report generation.

The base workflow is mandatory on top of domain tools: research, due diligence,
structured debate/adjudication, bounded execution, and evidence-based
iteration are recorded in the run trace and `plan.md`. A tool call without this
context is not a complete scientific run.

## Persistent campaign mode

When the user asks for an ongoing campaign, discovery program, or `/goal`-like
work, do not stop after the first two or three design rounds. Create a durable
run and treat three rounds as the first review checkpoint, not a completion
condition. Continue research, debate, bounded execution, independent QC, and
hypothesis revision until a predeclared quality gate has orthogonal support,
the user stops the campaign, or a concrete scientific/resource blocker
prevents meaningful progress. Each round needs a Worked / Why / Gap / Next
retrospective in `plan.md`. Resume the same run after interruption or context
compaction. Repeated “no hit” outcomes require a synthesis/pivot round that
changes the target hypothesis, conditioning, model, or confirmation strategy;
they are not permission to terminate silently.

## Non-Negotiable Operating Rules

- Start every scientific run with `proteinclaw_run_create` unless the user asks
  to continue an existing run, in which case call `proteinclaw_run_resume`.
- Pass the returned `run_id` to every ProteinClaw MCP tool that accepts it.
- Use ProteinClaw MCP tools for scientific execution. Do not reimplement
  RFdiffusion3, ProteinMPNN, ESMFold, AlphaFold2-multimer, interface metrics,
  target fetch/analyze, run artifacts, or report generation with ad hoc shell.
- Use native Codex web/search and native subagents for research, critique, and
  debate. ProteinClaw intentionally does not expose generic search or generic
  subagent tools.
- Record native research with `proteinclaw_research_record`. Record native
  critique/debate/adjudication with `proteinclaw_debate_record`. If it is not
  recorded, it will not be visible in the run trace or report.
- Read the relevant canonical skill before acting:
  `proteinclaw-minibinder`, `proteinclaw-nanobody`, each relevant
  `proteinclaw-tool-*`, and any matching `proteinclaw-learned-*`.
- Write run notes and retrospectives into run artifacts with
  `proteinclaw_artifact_write` so they land under the run directory. Use
  `path="plan.md"` and `append=true` for incremental notes.
- Treat computational outputs as design candidates, not validated binders.
  Be explicit about stubs, failed tools, skipped stages, OOMs, and weak gates.

## When To Ask The User

Make a reasonable assumption and proceed unless one of these is ambiguous:

- Target identity cannot be resolved to a specific protein, PDB, UniProt entry,
  sequence, or user-provided structure.
- Workflow choice is materially unclear: de-novo minibinder vs VHH/nanobody vs
  report-only/evaluation.
- Safety-critical constraints, forbidden target regions, species/isoform, or
  mutation requirements would change the design.
- The user requests a wet-lab, clinical, or deployment claim that cannot be
  supported by computational ProteinClaw outputs.

If asking, ask one concise question. Otherwise log assumptions in `plan.md` and
continue.

## Workflow Selection

Choose the workflow from the user request and target context:

- **Minibinder / de-novo binder**: use `proteinclaw-minibinder`. This is the
  RFdiffusion3 -> ProteinMPNN -> ESMFold -> AF2-multimer -> interface metrics
  pipeline. Use for generic protein surface binders, small designed binders,
  and epitope-directed de-novo designs.
- **Nanobody / VHH**: use `proteinclaw-nanobody`. This is VHH library
  generation -> ESMFold scaffold filter -> AF2-multimer screen -> AF-M
  confirmation -> CDR/interface metrics. Do not call RFdiffusion3 or
  ProteinMPNN in this workflow.
- **Evaluation/report-only**: if the user provides existing candidate PDBs,
  sequences, or a previous run, resume or create a run, record the context,
  use structure/analysis tools as needed, and generate a report. Do not invent
  a generation campaign unless asked.

When uncertain between minibinder and nanobody, default to minibinder unless
the user says nanobody, VHH, antibody fragment, camelid, CDR, or GPCR/VHH
screening.

## Run Lifecycle

1. Call `proteinclaw_run_create` with the original user prompt. Capture:
   `run_id`, `output_dir`, `workspace`, `plan_md`, `trace_jsonl`, `designs_dir`,
   and `report_html`.
2. Immediately create or append `plan.md` with:
   - Original request.
   - Workflow selected and why.
   - Target assumptions.
   - Design constraints and stop conditions.
   - Planned research questions and pipeline branch.
3. Use `proteinclaw_run_status` after major stages if paths or status are
   unclear.
4. Use `proteinclaw_run_finalize` only at the end or when abandoning the run.
   Use a blunt terminal status such as `completed`, `failed`, or
   `needs_human_review`.

Run artifacts are scoped. Use:

- `proteinclaw_artifact_read` for `plan.md`, `trace.jsonl`, `result.json`, and
  intermediate JSON/text outputs.
- `proteinclaw_artifact_write` for `plan.md`, scratch notes, and small helper
  artifacts under the run directory.
- `proteinclaw_artifact_search` to recover prior decisions after context
  compaction.

## Research And Debate Contract

Research and debate are mandatory before expensive design execution and again
before each meaningful refinement round.

### Research Fan-Out

Use native Codex web/search and native subagents to answer narrow questions.
Typical subtopics:

- Target identity, isoform, species, domain boundaries, and available PDBs.
- Known binding interfaces, co-crystal partners, hotspots, and epitope evidence.
- Target-specific liabilities: glycosylation, membrane embedding, disorder,
  missing loops, cofactors, ligands, oligomerization, or conformational state.
- Prior binder/nanobody campaigns, if any.
- Pipeline risk: expected target difficulty, crop strategy, and compute budget.

Record each useful research result:

```text
proteinclaw_research_record(
  run_id=<run_id>,
  source="native_web" or "native_subagent",
  query=<question>,
  summary=<evidence-backed conclusion>,
  citations=[...],
  notes=<confidence, caveats, what would change the plan>
)
```

Do not paste long papers into `plan.md`. Store concise claims, citations, and
decision impact.

### Due Diligence

Before debate, independently verify the claims that affect design:

- Fetch or inspect the target with `proteinclaw_data_rcsb_search`,
  `proteinclaw_data_uniprot_fetch`, `proteinclaw_data_pdb_fetch`, and
  `proteinclaw_data_pdb_analyze` as appropriate.
- Check chains, residue numbering, missing residues, non-protein HETATM/waters,
  confidence, interface residues, and whether the intended crop actually
  contains the target surface.
- For GPCRs or membrane proteins, preserve an intact receptor chain when the
  binder tool supports it and explicitly choose the extracellular or
  intracellular face and receptor state. A crop/soluble construct is allowed
  only when research and debate justify it; never crop by default or hide the
  transmembrane context from validation.

### Debate And Adjudication

Use native subagents or a structured main-agent critique to challenge the plan.
At minimum, debate the chosen epitope/crop and the workflow branch.

Record the result:

```text
proteinclaw_debate_record(
  run_id=<run_id>,
  subagent_type="native_subagent" or "main_agent_critique",
  prompt=<challenge>,
  position=<proposal being challenged>,
  summary=<critique/defense>,
  evidence=[...],
  decision=<what Codex will do next and why>
)
```

Adjudicate on evidence, not confidence. If debate changes the plan, append the
revised hypothesis to `plan.md`.

## Minibinder Execution Branch

Before using this branch, read `proteinclaw-minibinder` and the relevant tool
skills.

Canonical sequence:

1. **Resolve target and crop**
   - Use RCSB/UniProt/PDB tools and `proteinclaw_data_pdb_analyze`.
   - Select chain, residue span, and hotspots.
   - Verify protein span using ATOM records when crystal waters/ligands may
     share chain IDs.
   - Write the crop and hotspot rationale to `plan.md`.
2. **Generate backbones**
   - Read `proteinclaw-tool-rfdiffusion3`.
   - Call `proteinclaw_design_rfdiffusion3`.
   - Choose `num_designs` and `binder_length` from target difficulty and compute
     budget. Do not blindly copy defaults.
3. **Design sequences**
   - Read `proteinclaw-tool-proteinmpnn`.
   - Call `proteinclaw_design_proteinmpnn` on each viable backbone.
   - Prefer the soluble model for binder design when available.
4. **Monomer pre-filter**
   - Read `proteinclaw-tool-esmfold`.
   - Call `proteinclaw_structure_esmfold` in batches.
   - Drop obvious misfolders and low-complexity traps, but remember AF2 complex
     metrics are the decisive signal.
5. **Complex prediction**
   - Read `proteinclaw-tool-alphafold2-multimer`.
   - Call `proteinclaw_structure_alphafold2_multimer` for survivors.
   - Use broad triage first, then 5-model confirmation for top candidates before
     claiming hits.
6. **Interface analysis**
   - Read `proteinclaw-tool-interface-metrics`.
   - Call `proteinclaw_analysis_interface_metrics`.
   - For confirmed AF-M jobs, call `proteinclaw_analysis_afm_screen_score`.
7. **Gate and refine**
   - Apply the strict gate in `proteinclaw-minibinder` and report code:
     ipSAE, ipTM, binder/complex confidence, hotspot satisfaction, interface
     BSA, and clash sanity.
   - If weak, identify one bottleneck and run a bounded refinement round. Do not
     rerun the same parameters blindly.

## Nanobody Execution Branch

Before using this branch, read `proteinclaw-nanobody`,
`proteinclaw-tool-gpcr-target`, `proteinclaw-tool-boltzgen-nanobody`,
`proteinclaw-tool-boltz2-gpcr`, `proteinclaw-tool-alphafold2-multimer`, and the
interface/QC tool guidance.

Canonical sequence:

1. **Resolve target and epitope**
   - Preserve the intact GPCR and explicitly choose state and side.
   - Build `proteinclaw_data_gpcr_hypothesis_portfolio` from 2–8 distinct,
     evidence-grounded hypotheses before choosing the first GPU wave. Explore
     each shallowly and deep-dive only after one beats its matched control.
   - Supply the original mmCIF and, when RCSB provides one, the legacy PDB,
     plus author-numbered membrane spans,
     positive epitope anchors, and opposite-face `excluded_residues` to
     `proteinclaw_data_gpcr_target_prepare`.
     For mmCIF-only structures, omit `target_pdb`; target preparation creates
     the author-numbered compatibility PDB without losing canonical mapping.
   - Also supply construct/ligand context, unresolved and modelled regions,
     glycans, resolved state markers, experimental evidence, reference
     complexes/scaffolds, and counterstate structures. Require verified
     author-to-label mapping. Never delete a rejected binding mask to make
     generation run.
2. **Generate a small conditional set**
   - Call `proteinclaw_design_boltzgen_nanobody` with 8–16 designs and retain
     at most 4–8. The generated spec must contain both `binding` and
     `not_binding` masks on the label-numbered target chain.
3. **Fail-closed GPCR interface QC**
   - Call `proteinclaw_analysis_gpcr_candidate_qc` on every retained complex.
   - Calibrate BSA against a solved complex when available. Reject zero/weak
     hotspot satisfaction, any forbidden-face contact, severe clashes, and
     missing metrics.
4. **Calibrated orthogonal screen**
   - Run an exact experimentally validated binder and a matched control before
     candidate confirmation. If the known positive is not recovered, the model
     is uncalibrated and must not eliminate novel candidates.
   - Prefer `proteinclaw_structure_boltz2_gpcr` for state-dependent interfaces;
     it preserves the verified receptor template while leaving the binder pose
     untemplated. Keep candidate/control settings identical.
   - Sequence-only `proteinclaw_structure_alphafold2_multimer` is diagnostic
     unless it passes the same positive-control audit. It cannot establish
     active/inactive selectivity by itself.
5. **Replicated confirmation**
   - Re-run supported Boltz-2 candidates and controls with five diffusion
     samples. Compare sample distributions and intended-face recovery.
   - If AF-M is calibrated and used, re-run with `num_models=5` and call
     `proteinclaw_analysis_afm_screen_score` with both `output_dir` and
     `complex_pdb_path`.
6. **CDR/interface QC**
   - Call `proteinclaw_analysis_interface_metrics` with mapped hotspot
     residues and CDR ranges when available.
   - Fail framework-dominated interfaces, huge high-clash membrane artifacts,
     and candidates without reproducible model support.

`proteinclaw_design_nanobody_library` remains a controlled baseline or import
path. It is not the default GPCR generation route.

Do not call RFdiffusion3 or ProteinMPNN in nanobody workflows.

## Failure Handling

- Tool results are structured envelopes. If an envelope contains `"error"`,
  read `summary`, adjust parameters once, and retry at most once.
- If a GPU tool OOMs, reduce target crop, candidate count, model count, or
  recycle count. If it fails again, drop that branch and record why.
- Rate-limited research tools are degradation, not fatal. Proceed with native
  Codex research and record the gap.
- If target resolution remains uncertain after reasonable checks, stop before
  expensive GPU work and return `needs_human_review`.
- Never claim a design passed a gate unless the required metrics exist in
  `result.json`, trace, or tool envelopes.

## Skill Evolution

Promote durable lessons only when they change future behavior.

Use:

- `proteinclaw_skill_patch` for a precise correction.
- `proteinclaw_skill_write` for a clean rewrite of a skill.
- `proteinclaw_skill_create` for a focused `proteinclaw-learned-<topic>` skill.
- `proteinclaw_skill_append` only for a short note when preserving existing
  structure is better than rewriting.
- `proteinclaw_skill_delete` only when a learned/tool skill is obsolete or
  actively misleading. Do not delete core workflow skills unless the user asks.

Every written skill must start with YAML frontmatter containing matching
`name:` and non-empty `description:`. Perform the edit first, confirm the MCP
result, then mention the exact skill changed.

## Final Report And User Response

Before final user response:

1. Append a round retrospective to `plan.md`:
   - Worked
   - Why
   - Gap
   - Next
2. Call `proteinclaw_report_generate`.
3. Read or summarize `result.json` if available.
4. Finalize the run.

Return:

- `run_id`
- `report.html` path
- `result.json` path when present
- Top ranked designs and the metrics that matter
- Whether the strict gate was met
- Any caveats: stubs, OOMs, skipped confirmation, weak target resolution,
  low confidence, or need for human re-targeting

If no candidate passed, say so directly and explain the bottleneck. Do not
inflate a computational screen into experimental validation.

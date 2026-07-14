# MCP Tool Surface

ProteinClaw MCP tools are domain tools. They are not a replacement for Codex
planning, web browsing, terminal use, or subagents.

Tool names use:

```text
proteinclaw_<category>_<tool>
```

Every domain tool accepts `run_id` through the MCP wrapper so outputs are traced
to the active run.

## Run Lifecycle

- `proteinclaw_run_create`: create a run, workspace, trace, plan, report path,
  and designs directory.
- `proteinclaw_run_resume`: resume an existing run.
- `proteinclaw_run_status`: return run paths and status.
- `proteinclaw_run_list`: list known runs.
- `proteinclaw_run_finalize`: mark a run terminal.

Create or resume before any scientific tool call.

## Native Workflow Recorders

These record work Codex did outside ProteinClaw:

- `proteinclaw_research_record`: store native web/search/subagent research in
  `research.jsonl`, `plan.md`, and `trace.jsonl`.
- `proteinclaw_debate_record`: store native critique, defense, or adjudication
  in `debate.jsonl`, `plan.md`, and `trace.jsonl`.

They do not browse or spawn agents. Codex does that natively, then calls these
recorders.

## Run Artifacts

- `proteinclaw_artifact_read`: read a file under the run directory.
- `proteinclaw_artifact_write`: write or append a file under the run directory.
- `proteinclaw_artifact_search`: search text files under the run directory.

Use these for `plan.md`, scratch notes, and run-local analysis artifacts. They
prevent accidental writes outside the run directory.

## Data And Research Tools

- `proteinclaw_data_rcsb_search`: find candidate PDB structures.
- `proteinclaw_data_uniprot_fetch`: fetch sequence and metadata.
- `proteinclaw_data_pdb_fetch`: fetch and optionally crop a PDB.
- `proteinclaw_data_pdb_analyze`: inspect chains, residues, gaps, interfaces,
  confidence, and hotspots.
- `proteinclaw_research_literature_search`: LitSense/PubMed style literature
  helper.
- `proteinclaw_research_pubmed_search`: PubMed/NCBI helper.

Native Codex browsing remains the primary general web mechanism. These helpers
exist for domain-specific retrieval and traceable run evidence.

## Design And Structure Tools

Minibinder branch:

- `proteinclaw_design_rfdiffusion3`: backbone generation.
- `proteinclaw_design_proteinmpnn`: sequence design on generated backbones.
- `proteinclaw_structure_esmfold`: monomer pre-filter.
- `proteinclaw_structure_alphafold2_multimer`: binder-target complex
  prediction.

Nanobody branch:

- `proteinclaw_data_gpcr_hypothesis_portfolio`: validate 2–8 distinct,
  experimentally grounded state/epitope hypotheses, counterstate/reference
  structures, observed scaffold priors, falsifiable predictions, and matched
  controls; emit a shallow exploration plan and gated deep-dive budget.
- `proteinclaw_data_gpcr_target_prepare`: validate and stage an intact,
  state-annotated GPCR chain, verified mmCIF residue mapping, researched
  epitope, membrane spans, forbidden-face controls, unresolved/modelled regions,
  glycans, construct/ligand context, state markers, and evidence provenance.
  Legacy PDB input is optional; mmCIF-only entries are converted to a
  single-author-chain compatibility PDB while mmCIF remains authoritative.
- `proteinclaw_design_boltzgen_nanobody`: bounded BoltzGen nanobody design
  round with simultaneous binding/not-binding masks (small hypothesis set;
  resumable).
- `proteinclaw_design_nanobody_library`: generate or import VHH library.
- `proteinclaw_structure_esmfold`: VHH scaffold sanity check.
- `proteinclaw_structure_alphafold2_multimer`: VHH-target complex screen.
- `proteinclaw_structure_boltz2_gpcr`: state-conditioned GPCR/VHH complex
  confirmation using the verified receptor template, mapped epitope pocket,
  physical-quality potentials, and 1–5 diffusion samples. Calibrate it on a
  known positive and matched control before candidate elimination.
- `proteinclaw_structure_gpcr_pose_refine`: solved-pose homolog transfer,
  evidence-backed VHH mutation grafting, and restrained OpenMM refinement.

Do not call RFdiffusion3 or ProteinMPNN for the nanobody workflow.

## Analysis Tools

- `proteinclaw_analysis_interface_metrics`: deterministic geometric/interface
  QC on a predicted complex.
- `proteinclaw_analysis_gpcr_candidate_qc`: fail-closed GPCR/VHH QC against the
  target manifest's mapped positive and forbidden-face residues.
- `proteinclaw_analysis_afm_screen_score`: aggregate 5-model AF-M confirmation
  outputs for model-support and combo ranking.
- `proteinclaw_analysis_binding_affinity`: advisory KD/dG estimate. Never use
  this as a pass/fail gate by itself.

Quality gates are defined in the workflow skills and report code. AF2 pLDDT
alone is not enough.

## Skill Tools

- `proteinclaw_skill_list`
- `proteinclaw_skill_read`
- `proteinclaw_skill_append`
- `proteinclaw_skill_create`
- `proteinclaw_skill_write`
- `proteinclaw_skill_patch`
- `proteinclaw_skill_delete`

These are scoped to `skills/proteinclaw-*`. Use them only for durable,
generalizable procedural memory. Run-specific facts belong in `plan.md`.

## Report Tool

- `proteinclaw_report_generate`: parse trace and run artifacts, stage ranked
  designs, write `result.json`, and render `report.html`.

Run this before the final user response whenever a scientific run was executed
or evaluated.

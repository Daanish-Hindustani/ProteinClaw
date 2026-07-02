# Architecture

ProteinClaw is a Codex plugin that exposes protein binder design capabilities
through an MCP server. It is intentionally not a standalone agent. Codex owns
planning, web research, file inspection, shell work, and subagent orchestration.
ProteinClaw owns domain tools, run lifecycle, durable artifacts, skill guidance,
and report generation.

## System Model

```text
User request
  -> Codex
    -> loads ProteinClaw Codex plugin
      -> reads packaged skills from ./skills/
      -> starts MCP server from ./.mcp.json
        -> python -m proteinclaw.agent.mcp_server
          -> run lifecycle tools
          -> research/debate recorders
          -> scientific tool registry
          -> local or Docker-backed execution
          -> report generation
```

The plugin manifest is `.codex-plugin/plugin.json`. It advertises:

- `./skills/` for Codex workflow and tool guidance.
- `./.mcp.json` for the MCP server launch command.

The MCP server communicates over stdio and starts with:

```bash
uv run --project . python -m proteinclaw.agent.mcp_server
```

Companion docs:

- `docs/agent-platform-install.md` covers Codex plugin installation, reload,
  and validation.
- `docs/mcp-tool-surface.md` lists the MCP tool families and their boundaries.
- `docs/gpu-docker-setup.md` covers GPU/container runtime assumptions.
- `docs/repository-tree.md` maps repository ownership and public contract files.
- `docs/plugin-migration-removal-audit.md` records what was kept, refactored,
  or removed during the plugin migration.

## Responsibility Split

ProteinClaw keeps generic agent behavior out of the MCP server on purpose.

Codex is responsible for:

- Interpreting the user request.
- Asking clarification questions when the target, workflow, constraints, or
  safety-critical assumptions are ambiguous.
- Reading packaged skills and deciding the workflow.
- Native web/search and literature browsing.
- Native subagents for research, critique, and debate.
- General shell/file inspection outside ProteinClaw run artifacts.
- Final adjudication and user-facing explanation.

ProteinClaw MCP is responsible for:

- Creating and resuming scoped runs.
- Fetching and analyzing target structures and sequences.
- Running scientific pipeline tools.
- Recording Codex-native research and debate into run artifacts.
- Managing scoped ProteinClaw skill updates.
- Generating reports from trace and run outputs.

This split matters: ProteinClaw does not expose generic web search, generic
subagents, or a replacement planning loop. Codex already has those capabilities.

## End-to-End Workflow

A typical Codex-driven ProteinClaw run follows this control flow:

```text
1. Load plugin skills
2. Create or resume ProteinClaw run
3. Resolve target identity and constraints
4. Run native research fan-out with Codex subagents
5. Record research evidence into ProteinClaw artifacts
6. Run due-diligence checks with Codex plus ProteinClaw data tools
7. Debate contested hypotheses with native subagents
8. Record debate/adjudication into ProteinClaw artifacts
9. Execute scientific pipeline through MCP tools
10. Triage designs and decide whether to refine
11. Optionally update scoped skills with durable lessons
12. Generate final report and return ranked candidates
```

Every scientific run starts with `proteinclaw_run_create` or
`proteinclaw_run_resume`. Domain tools require `run_id` so outputs remain scoped
to one run directory.

## Research Fan-Out

Research fan-out is native Codex work, not ProteinClaw MCP work. Codex should
use its own search and subagent mechanisms to gather evidence before expensive
pipeline execution.

Typical research subtopics include:

- Prior binder campaigns or structural biology for the target.
- Fold-family and topology precedent.
- Known binding interfaces, epitopes, or co-crystal evidence.
- Developability, expression, or immunogenicity liabilities.
- Failure analysis from previous ProteinClaw rounds.

Each research subagent should return one falsifiable hypothesis with citations,
confidence, and what would disprove it. Subagents are advisors only. Codex must
verify important claims with its own web/literature checks and structural
inspection.

After research, Codex calls `proteinclaw_research_record` with the query,
summary, citations, and notes. ProteinClaw writes this to `research.jsonl`,
`plan.md`, and `trace.jsonl` so the final report can prove why decisions were
made.

## Due Diligence

Due diligence is the main-agent verification step between research and debate.
It prevents subagent output from becoming unreviewed authority.

Codex should verify claims through two channels:

- Independent web/literature review using native Codex tools and ProteinClaw
  literature/PubMed tools when useful.
- Structural inspection using `proteinclaw_data_pdb_analyze`, plus short scratch
  analysis under the run directory when the MCP summary is insufficient.

ProteinClaw’s structural tools handle chain summaries, residue ranges, gaps,
hotspot presence, confidence statistics, and interface metrics. Codex can use
scratch scripts for narrow checks such as contact counts or residue accessibility,
but the scientific pipeline stages themselves should remain MCP tool calls.

## Debate and Adjudication

Debate is also native Codex work. ProteinClaw records it but does not run it.

The debate loop is deliberately bounded:

- Identify contested claims between research subagents, structural evidence, and
  previous-round metrics.
- Challenge a contested claim once with a native subagent in defend/revise mode.
- Compare the defense against citations, structural data, and pipeline results.
- Adjudicate on evidence, not on which subagent sounded most confident.
- Choose one design hypothesis for the next pipeline round.

For refinement rounds, Codex should carry forward concrete metrics from earlier
rounds: ipSAE, ipTM, complex pLDDT, hotspot satisfaction, buried surface area,
clashes, and the previous hypothesis. The next hypothesis should visibly explain
what changed and why.

After debate, Codex calls `proteinclaw_debate_record` with the challenge,
position, summary, evidence, and decision. ProteinClaw writes this to
`debate.jsonl`, `plan.md`, and `trace.jsonl`.

## Scientific Pipeline

ProteinClaw scientific tools live under `src/proteinclaw/tools/`. Each tool owns
its schema, implementation, and optional Docker runtime metadata. The MCP server
wraps these tools with the `proteinclaw_<category>_<tool>` naming convention.

Common pipeline tools include:

- `proteinclaw_data_rcsb_search`
- `proteinclaw_data_uniprot_fetch`
- `proteinclaw_data_pdb_fetch`
- `proteinclaw_data_pdb_analyze`
- `proteinclaw_research_literature_search`
- `proteinclaw_research_pubmed_search`
- `proteinclaw_design_rfdiffusion3`
- `proteinclaw_design_proteinmpnn`
- `proteinclaw_structure_esmfold`
- `proteinclaw_structure_alphafold2_multimer`
- `proteinclaw_analysis_interface_metrics`
- `proteinclaw_analysis_afm_screen_score`
- `proteinclaw_analysis_binding_affinity`
- `proteinclaw_artifact_read`
- `proteinclaw_artifact_write`
- `proteinclaw_report_generate`

`ComputeRouter` decides whether a tool runs locally or through Docker. GPU tools
depend on Docker and NVIDIA GPU access. Default tests do not require GPU, Docker,
or live network access.

Codex should not reimplement these stages with ad hoc shell scripts. Scratch
scripts are acceptable for inspection, but pipeline outputs should come from MCP
tools so traces and reports remain consistent.

## Refinement Loop

ProteinClaw workflows are iterative. A round may produce weak or failed designs;
that is expected. The next round should not blindly rerun the same parameters.

A refinement round should:

- Read the prior run artifacts and metrics.
- Identify the bottleneck: docking, fold confidence, hotspot satisfaction,
  clashes, buried surface area, developability, or target resolution.
- Re-task research or critique around that bottleneck.
- Debate the revised hypothesis.
- Change one meaningful design variable at a time when practical.
- Stop when the skill-defined quality gate is met or when bounded retries are
  exhausted.

This loop keeps failures auditable and prevents unbounded retry behavior.

## Runs and Artifacts

Runs are directory-based. `PROTEINCLAW_RUNS_DIR` controls the output root. The
current plugin config sets it to `./runs`, which resolves relative to the MCP
server launch working directory. Operators can set it to a stable absolute path,
such as `~/.proteinclaw/runs`, for installed plugin deployments.

A run may contain:

- `run.json`
- `plan.md`
- `trace.jsonl`
- `research.jsonl`
- `debate.jsonl`
- `result.json`
- `report.html`
- `designs/`
- `scratch/`
- intermediate tool outputs

Generated runs are runtime artifacts. They should not be committed unless a
small file is intentionally promoted into `tests/fixtures/`.

## Trace and Report Model

The trace is the audit backbone. ProteinClaw records:

- Run lifecycle events.
- MCP tool calls.
- Native research records.
- Native debate/adjudication records.
- Skill updates.
- Report generation.

`proteinclaw_report_generate` converts run artifacts into `report.html`. The
report should explain not only the final ranked candidates, but also the research
evidence, debate decisions, pipeline stages, and round-to-round reasoning.

## Skill Layer

Codex skills live under top-level `skills/`. They define the operating policy
for workflows, tool-specific guidance, and durable learned lessons.

Important skill categories:

- `proteinclaw-workflow`: high-level Codex/ProteinClaw operating model.
- `proteinclaw-minibinder`: de novo RFdiffusion3 minibinder workflow.
- `proteinclaw-nanobody`: VHH/nanobody workflow.
- `proteinclaw-tool-*`: operational guidance for individual tool families.
- `proteinclaw-learned-*`: durable lessons learned across runs.

Skill files must use valid YAML frontmatter. ProteinClaw skill mutation tools
are scoped to the plugin skill namespace and validate frontmatter before writing.

## Safety and Boundaries

ProteinClaw does not:

- Manage model-provider credentials.
- Replace Codex planning, web search, shell, or subagent capabilities.
- Expose generic web search or generic subagent MCP tools.
- Treat computational outputs as experimentally validated results.
- Commit generated run directories as part of the package.

ProteinClaw outputs are computational candidates. They require scientific
review, wet-lab validation, and safety review before any downstream use.

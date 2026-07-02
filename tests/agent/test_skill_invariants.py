"""Regression: lock in the critical guidance in skills/proteinclaw-minibinder/SKILL.md.

These tests assert that key strings the agent relies on remain present
in the skill file. They are *intentionally fragile* — if you edit the
skill file and a test breaks, decide whether the change is meant to
remove the guarantee or whether you need to keep the same intent in
new wording. If the former, delete the failing assertion + write a
NOTES.md entry explaining why.
"""

from __future__ import annotations

import re

from proteinclaw.agent.skills import _SKILL_PATH, load_skill_text


def _all_skill_text() -> str:
    """Core skill + every per-tool skill file.

    Steps 4–7 detail now lives in ``skills/proteinclaw-tool-*/SKILL.md``
    (progressive disclosure). Invariants about tool-specific guidance check
    the whole surface the agent can reach, not just the core file.
    """
    parts = [load_skill_text()]
    skill_root = _SKILL_PATH.parents[1]
    parts += [f.read_text(encoding="utf-8") for f in sorted(skill_root.glob("proteinclaw-tool-*/SKILL.md"))]
    return "\n".join(parts)


def test_lists_every_domain_tool_name() -> None:
    text = load_skill_text()
    required = [
        "proteinclaw_data_rcsb_search",
        "proteinclaw_data_uniprot_fetch",
        "proteinclaw_data_pdb_fetch",
        "proteinclaw_data_pdb_analyze",
        "proteinclaw_research_literature_search",
        "proteinclaw_research_pubmed_search",
        "proteinclaw_design_rfdiffusion3",
        "proteinclaw_design_proteinmpnn",
        "proteinclaw_structure_esmfold",
        "proteinclaw_structure_alphafold2_multimer",
    ]
    missing = [t for t in required if t not in text]
    assert not missing, f"skill file dropped tool names: {missing}"


def test_emphasises_ranking_signal() -> None:
    """PRD §6.6 — the AF2 complex pLDDT is THE ranking signal."""
    text = load_skill_text().lower()
    assert "ranking signal" in text
    assert "complex_confidence" in text or "complex pldlt" in text or "complex pLDDT".lower() in text


def test_caps_retries() -> None:
    """No infinite-loop risk — every retry has a bound."""
    text = load_skill_text().lower()
    assert "at most once" in text or "at most one retry" in text
    assert "never enter a retry loop" in text or "do not enter a retry loop" in text


def test_documents_built_in_tool_policy() -> None:
    """Built-ins are now ENCOURAGED for inspection but MCP tools remain
    canonical for pipeline stages. Skill must spell both halves out."""
    text = load_skill_text().lower()
    # MCP tools are canonical for the pipeline. v3 wording: "Canonical
    # for every pipeline stage" (with the line break + indent that
    # markdown reflow introduces).
    import re
    assert re.search(r"canonical\s+for every pipeline", text), \
        "skill should declare MCP tools canonical for the pipeline"
    # Built-ins are explicitly allowed for inspection / scratch.
    for token in ["bash", "read", "write", "grep", "webfetch", "websearch"]:
        assert token in text, f"skill should reference built-in {token!r}"
    # And there's a guardrail: scratch goes to ./scratch/, not deliverables.
    assert "./scratch/" in text or "scratch" in text


def test_mcp_tools_still_canonical_for_pipeline() -> None:
    """Built-in liberty must not undermine the pipeline-via-MCP rule."""
    text = load_skill_text()
    # The pipeline list still uses proteinclaw_ names.
    assert "proteinclaw_design_rfdiffusion3" in text
    assert "proteinclaw_structure_alphafold2_multimer" in text
    # And the no-reinvention rule is explicit.
    txt = text.lower()
    assert "do not reinvent" in txt or "do not invent" in txt or "do not replace" in txt or "do not roll your own" in txt or "reinvent" in txt


def test_documents_msa_degraded_handling() -> None:
    """msa_degraded must NOT be silently treated as comparable to colabfold.

    The `msa_degraded` field token lives in tools/alphafold2_multimer.md;
    the "listed separately" triage rule lives in the core step-8 summary.
    """
    text = _all_skill_text().lower()
    assert "msa_degraded" in text
    # v3 phrasing: "don't rank them alongside" / "listed separately".
    assert (
        "don't rank them alongside" in text
        or "do not rank degraded results alongside" in text
        or "listed separately" in text
    )


def test_documents_rfd3_chain_detection() -> None:
    """Agent must read output_binder_chain from envelope, not assume.

    Detail now lives in tools/rfdiffusion3.md (progressive disclosure).
    """
    text = _all_skill_text().lower()
    assert "output_binder_chain" in text
    # Skill must explicitly warn against assuming a chain letter.
    assert "never assume" in text or "do not assume" in text


def test_documents_af2_target_sequence_cap() -> None:
    """Don't pass full UniProt chain to AF2 — use the crop.

    Detail now lives in tools/alphafold2_multimer.md.
    """
    text = _all_skill_text()
    # The skill must instruct to use the crop, not the full UniProt chain.
    assert "SAME crop" in text or "not the full UniProt chain" in text
    assert "1024" in text  # the AF2 cap is mentioned for context


def test_documents_esmfold_field_name() -> None:
    """Agent shouldn't have to guess which field holds the pLDDT.

    Detail now lives in tools/esmfold.md.
    """
    text = _all_skill_text()
    # We named the field `confidence` (per esmfold/implementation.py).
    # The skill must reference it directly so the agent doesn't hallucinate.
    assert re.search(r"predictions\[.*\]\.confidence|`confidence`", text)


def test_length_is_reasonable() -> None:
    """Sanity: not too short (ambiguous), not too long (skim-read).

    Upper bound raised to 48k as the skill grew the hypothesis-driven
    sections (research fan-out, due diligence, debate, self-refining
    loop) on top of the antibody / key-residue + ipSAE content. Still a
    guard against unbounded bloat.
    """
    chars = len(load_skill_text())
    assert 5_000 <= chars <= 48_000, f"skill length {chars} outside 5k-48k window"


def test_documents_research_fanout_hypotheses() -> None:
    """Research/debate uses the host agent's native subagent mechanism."""
    text = load_skill_text()
    low = text.lower()
    assert "native" in low and "subagent" in low
    assert "research_scout" not in text
    assert "evidence-backed hypothesis" in low
    # The durable-memory notebook is plan.md (unified from the old
    # hypotheses.md), and there's a guardrail against touching the repo's
    # NOTES.md.
    assert "plan.md" in text
    assert "notes.md" in low  # the off-limits guardrail still names NOTES.md


def test_documents_due_diligence_both_checks() -> None:
    """Due diligence requires BOTH the agent's own web/lit search AND
    Bash/scratch structural analysis — subagents are advisors, not authorities."""
    low = load_skill_text().lower()
    assert "due diligence" in low
    # Own independent web/lit verification.
    assert "websearch" in low and "literature_search" in low
    # Structural sandbox analysis via Bash + scratch.
    assert "bash" in low and "./scratch/" in low


def test_documents_debate_adjudication() -> None:
    """The agent debates native research subagents and adjudicates on evidence."""
    low = load_skill_text().lower()
    assert "debate" in low
    assert "challenge" in low and "defend" in low
    assert "adjudicate on evidence, not authority" in low
    # Anti-thrash bound: one challenge->defense exchange per contested claim.
    assert "one challenge→defense exchange per" in low or "at most one challenge" in low


def test_documents_subagent_refusal_escalation() -> None:
    """On a usage-policy refusal, retry once with stronger native controls."""
    low = load_skill_text().lower()
    assert "usage-policy" in low or "usage policy" in low
    assert "stronger model" in low
    assert "retry" in low and "once" in low


def test_documents_self_refining_loop() -> None:
    """Refine-on-bad loop: re-task research, improved hypothesis, never repeat."""
    low = load_skill_text().lower()
    assert "re-task" in low
    assert "improved hypothesis" in low
    assert "never repeat" in low


def test_antibody_content_removed_from_core() -> None:
    """Antibody *design* (§9: RFantibody, ANARCI/IMGT numbering, scFv/VHH) was
    removed from the **mini-binder core prose** — separate model family, out of
    scope for the de-novo mini-binder pipeline. Note: generic interface terms
    ("paratope/epitope") and the "freesasa is NOT in the base image" warning are
    intentionally KEPT.

    Checks the minibinder skill's own body (NOT ``load_skill_text()``): the appended
    Tool skill index now legitimately lists ``proteinclaw-tool-nanobody-library``
    after the nanobody workflow landed, so the guarantee is about the mini-binder
    core skill's *prose*, not the shared tool-file index. (NOTES.md 2026-06-21.)"""
    low = _SKILL_PATH.read_text(encoding="utf-8").lower()
    body = low.split("---", 2)[-1] if low.startswith("---") else low
    for token in ["antibody", "nanobod", "rfantibody", "anarci", "imgt", "scfv", "vhh"]:
        assert token not in body, f"core skill still references removed token {token!r}"


def test_core_skill_uses_plan_md_not_hypotheses_md() -> None:
    """The run notebook is unified under plan.md (was hypotheses.md)."""
    text = load_skill_text()
    assert "plan.md" in text
    assert "hypotheses.md" not in text, "skill still references the old hypotheses.md name"


def test_tool_skill_index_lists_absolute_paths() -> None:
    """load_skill_text appends an index pointing at each tool file's abs path
    so the agent's on-demand Read resolves from the run-dir cwd."""
    text = load_skill_text()
    assert "Tool skill index" in text
    for skill in [
        "proteinclaw-tool-rfdiffusion3",
        "proteinclaw-tool-proteinmpnn",
        "proteinclaw-tool-esmfold",
        "proteinclaw-tool-alphafold2-multimer",
    ]:
        assert re.search(rf"/skills/{re.escape(skill)}/SKILL\.md`", text), f"index missing abs path for {skill}"


def test_core_step_summaries_point_to_tool_files() -> None:
    """Steps 4–7 must instruct the agent to Read the tool skill file first."""
    text = load_skill_text()
    for skill in [
        "proteinclaw-tool-rfdiffusion3",
        "proteinclaw-tool-proteinmpnn",
        "proteinclaw-tool-esmfold",
        "proteinclaw-tool-alphafold2-multimer",
    ]:
        assert skill in text
    assert "Read the tool skill file before each pipeline tool step" in text


def test_documents_self_evolution() -> None:
    """Optional self-evolution of the global skills."""
    text = load_skill_text()
    low = text.lower()
    assert "## Self-evolution" in text
    assert "clean procedural memory" in low
    assert "proteinclaw-learned-" in text             # where new skills go
    assert "proteinclaw_skill_write" in text          # scoped MCP self-evolution tools
    assert "proteinclaw_skill_patch" in text
    assert "proteinclaw_skill_create" in text
    assert "proteinclaw_skill_delete" in text
    assert "frontmatter" in low
    # The "do NOT write outside the run dir" rule now carries the skill-edit
    # carve-out (otherwise self-evolution contradicts it).
    assert "one exception" in low
    # Self-evolution is optional/rare, not every run.
    assert "optional" in low


def test_skill_files_under_size_cap() -> None:
    """Self-evolution can rewrite skills; guard against unbounded bloat."""
    from proteinclaw.agent.skills import plugin_skills_root

    for md in plugin_skills_root().rglob("SKILL.md"):
        size = len(md.read_text(encoding="utf-8"))
        assert size < 60_000, f"{md.name} is {size} chars (>60k cap)"

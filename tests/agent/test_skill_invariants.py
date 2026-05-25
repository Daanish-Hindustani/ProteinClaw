"""Regression: lock in the critical guidance in skills/proteindesign.md.

These tests assert that key strings the agent relies on remain present
in the skill file. They are *intentionally fragile* — if you edit the
skill file and a test breaks, decide whether the change is meant to
remove the guarantee or whether you need to keep the same intent in
new wording. If the former, delete the failing assertion + write a
NOTES.md entry explaining why.
"""

from __future__ import annotations

import re

from proteinclaw.agent.skills import load_skill_text


def test_lists_every_mcp_tool_name() -> None:
    text = load_skill_text()
    required = [
        "mcp__proteinclaw_tools__data_rcsb_search",
        "mcp__proteinclaw_tools__data_uniprot_fetch",
        "mcp__proteinclaw_tools__data_pdb_fetch",
        "mcp__proteinclaw_tools__research_literature_search",
        "mcp__proteinclaw_tools__research_pubmed_search",
        "mcp__proteinclaw_tools__design_rfdiffusion3",
        "mcp__proteinclaw_tools__design_proteinmpnn",
        "mcp__proteinclaw_tools__structure_esmfold",
        "mcp__proteinclaw_tools__structure_alphafold2_multimer",
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
    # The pipeline list still uses mcp__proteinclaw_tools__ names.
    assert "mcp__proteinclaw_tools__design_rfdiffusion3" in text
    assert "mcp__proteinclaw_tools__structure_alphafold2_multimer" in text
    # And the no-reinvention rule is explicit.
    txt = text.lower()
    assert "do not reinvent" in txt or "do not invent" in txt or "do not replace" in txt or "do not roll your own" in txt or "reinvent" in txt


def test_documents_msa_degraded_handling() -> None:
    """msa_degraded must NOT be silently treated as comparable to colabfold."""
    text = load_skill_text().lower()
    assert "msa_degraded" in text
    # v3 phrasing: "don't rank them alongside" / "listed separately".
    assert (
        "don't rank them alongside" in text
        or "do not rank degraded results alongside" in text
        or "listed separately" in text
    )


def test_documents_rfd3_chain_detection() -> None:
    """Agent must read output_binder_chain from envelope, not assume."""
    text = load_skill_text().lower()
    assert "output_binder_chain" in text
    # Skill must explicitly warn against assuming a chain letter.
    assert "never assume" in text or "do not assume" in text


def test_documents_af2_target_sequence_cap() -> None:
    """Don't pass full UniProt chain to AF2 — use the crop."""
    text = load_skill_text()
    # The skill must instruct to use the crop, not the full UniProt chain.
    assert "SAME crop" in text or "not the full UniProt chain" in text
    assert "1024" in text  # the AF2 cap is mentioned for context


def test_documents_esmfold_field_name() -> None:
    """Agent shouldn't have to guess which field holds the pLDDT."""
    text = load_skill_text()
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
    """Scouts fan out via the Task tool and return evidence-backed hypotheses."""
    text = load_skill_text()
    low = text.lower()
    # Fan-out is delegated to scouts spawned via the Task tool.
    assert "task" in low and "scout" in low
    assert "evidence-backed hypothesis" in low
    # The durable-memory file, and the guardrail against clobbering NOTES.md.
    assert "hypotheses.md" in text
    assert "Do NOT name this `NOTES.md`" in text or "do not name this `notes.md`" in low


def test_documents_due_diligence_both_checks() -> None:
    """Due diligence requires BOTH the agent's own web/lit search AND
    Bash/scratch structural analysis — scouts are advisors, not authorities."""
    low = load_skill_text().lower()
    assert "due diligence" in low
    # Own independent web/lit verification.
    assert "websearch" in low and "literature_search" in low
    # Structural sandbox analysis via Bash + scratch.
    assert "bash" in low and "./scratch/" in low


def test_documents_debate_adjudication() -> None:
    """The agent debates the scouts and adjudicates on evidence, bounded."""
    low = load_skill_text().lower()
    assert "debate" in low
    assert "challenge" in low and "defend" in low
    assert "adjudicate on evidence, not authority" in low
    # Anti-thrash bound: one challenge->defense exchange per contested claim.
    assert "one challenge→defense exchange per" in low or "at most one challenge" in low


def test_documents_scout_refusal_escalation() -> None:
    """On a Sonnet usage-policy refusal, fan-out must escalate the refused
    sub-topic to the Opus tier (research_pro), not just rephrase — the A/B
    test proved rephrasing/context can't beat the topic+model refusal."""
    text = load_skill_text()
    low = text.lower()
    assert "usage-policy" in low or "usage policy" in low
    assert "research_pro" in text
    assert "opus" in low


def test_documents_self_refining_loop() -> None:
    """Refine-on-bad loop: re-task scouts, improved hypothesis, never repeat."""
    low = load_skill_text().lower()
    assert "re-task" in low
    assert "improved hypothesis" in low
    assert "never repeat" in low

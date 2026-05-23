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
        "mcp__proteinclaw_tools__research_web_search",
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


def test_warns_against_built_in_tools() -> None:
    """Agent must use our MCP tools, not Bash/Read/Write/etc."""
    text = load_skill_text().lower()
    assert "bash" in text and "writefetch" not in text  # sanity
    # The skill mentions the do-not-use list:
    for token in ["bash", "read", "write", "webfetch", "websearch", "task"]:
        assert token in text, f"skill should mention not to use built-in {token!r}"


def test_documents_msa_degraded_handling() -> None:
    """msa_degraded must NOT be silently treated as comparable to colabfold."""
    text = load_skill_text().lower()
    assert "msa_degraded" in text
    assert "do not rank degraded results alongside" in text


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
    """Sanity: not too short (ambiguous), not too long (skim-read)."""
    chars = len(load_skill_text())
    assert 5_000 <= chars <= 20_000, f"skill length {chars} outside 5k-20k window"

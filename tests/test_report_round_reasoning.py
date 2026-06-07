"""Round-by-round reasoning card — parses plan.md round retrospectives.

The agent writes a per-round retrospective block to plan.md (skill
§Self-refining loop). The report surfaces it as a scannable card so the
"this worked because X → new hypothesis" reasoning isn't buried in the
verbatim plan.md dump.
"""

from __future__ import annotations

from proteinclaw.report import _parse_round_reasoning, _render_round_reasoning

_PLAN = """# TREM2 run

## Round-by-round outcomes

### Round 1 — cold start, ipSAE 0.806
- **Worked:** CDR2 helical bundle, BSA 1136 Å²
- **Why:** A44/A74/A76 all contacted by the long helix
- **Gap:** A78 unsatisfied (hotspot 75%) — bundle can't reach it
- **Next hypothesis:** extend the C-term helix by ~12 aa to reach A78

### Round 2 — partial_t=3 polish, ipSAE 0.828
- Worked: partial diffusion of R1-8 winner
- Why: tightened the existing interface without losing the fold
- Gap: ipSAE plateaued; A78 still the limiter
- Next: pivot epitope to drop A78, add A98 contact
"""


def test_parse_round_reasoning_extracts_two_rounds() -> None:
    rounds = _parse_round_reasoning(_PLAN)
    assert len(rounds) == 2
    r1 = rounds[0]
    assert r1["round"] == "1"
    assert "cold start" in r1["title"]
    # Exact values — no leftover markdown ** markers from "**Worked:**".
    assert r1["worked"] == "CDR2 helical bundle, BSA 1136 Å²"
    assert not any(r1[f].startswith("*") for f in ("worked", "why", "gap", "next_hypothesis"))
    assert "A44/A74/A76" in r1["why"]
    assert "A78 unsatisfied" in r1["gap"]
    assert "extend the C-term helix" in r1["next_hypothesis"]


def test_parse_round_reasoning_tolerates_bold_bullets_and_next_alias() -> None:
    # Round 2 uses plain "Worked:" (no bold/bullet) and "Next:" alias.
    r2 = _parse_round_reasoning(_PLAN)[1]
    assert r2["round"] == "2"
    assert "partial diffusion" in r2["worked"]
    assert "pivot epitope" in r2["next_hypothesis"]


def test_parse_round_reasoning_none_without_round_sections() -> None:
    assert _parse_round_reasoning("# Plan\n\nGeneric notes, no rounds.") == []


def test_parse_round_reasoning_skips_round_headers_without_fields() -> None:
    # A round heading with no recognised retrospective fields is not surfaced
    # (the verbatim plan.md card still shows it).
    plan = "### Round 1 — just a title\n- some bullet\n- another bullet\n"
    assert _parse_round_reasoning(plan) == []


def test_render_round_reasoning_card_has_rounds_and_escapes() -> None:
    out = _render_round_reasoning(_PLAN)
    assert "Round-by-round reasoning" in out
    assert "Round 1" in out and "Round 2" in out
    # field labels rendered
    assert "Worked" in out and "Next hypothesis" in out
    # content present and HTML-escaped (Å² text passes through; angle brackets escaped)
    assert "CDR2 helical bundle" in out


def test_render_round_reasoning_empty_when_no_rounds() -> None:
    assert _render_round_reasoning("# Plan\n\nno rounds here") == ""


def test_render_round_reasoning_escapes_html() -> None:
    plan = (
        "### Round 1 — t\n"
        "- Worked: <script>alert(1)</script> fold\n"
    )
    out = _render_round_reasoning(plan)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out

"""Single-file ``report.html`` renderer — modern card-based UI.

Inputs: a ``TriageResult`` (from ``agent/triage.py``). Outputs: a
self-contained HTML file with:
  * Sticky top bar (run id, target, cost, elapsed, ranked-count)
  * Hero card showcasing the rank-1 design + its key metrics
  * Pipeline summary strip (RFD3 → MPNN → ESM → AF2, counts at each stage)
  * Card-grid of ranked designs with per-residue pLDDT visualisation
    (colored cell per residue) and per-card metrics
  * ESM-vs-AF2 scatter (inline SVG, with "fold & dock" / "fold-only"
    quadrant labels)
  * Mol* viewer of the top design (PDB inlined into a JS var; loads
    from a CDN, so an active internet connection is needed on first
    open; cached by the browser thereafter)
  * Collapsible run-trace section with stage timings

External deps: Mol* via cdn.jsdelivr.net. Everything else (CSS, SVG,
PDB text, per-residue scores) is inlined.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Optional

from proteinclaw.agent.triage import DesignRecord, TriageResult


_MOLSTAR_JS = "https://cdn.jsdelivr.net/npm/molstar@latest/build/viewer/molstar.js"
_MOLSTAR_CSS = "https://cdn.jsdelivr.net/npm/molstar@latest/build/viewer/molstar.css"


def render_report(
    triage: TriageResult,
    *,
    run_id: str,
    prompt: str,
    output_path: Path,
    extra_meta: Optional[dict[str, Any]] = None,
) -> Path:
    """Render ``report.html`` and return its path."""
    meta = extra_meta or {}
    ranked = triage.ranked_designs
    top = ranked[0] if ranked else None
    top_pdb_text = ""
    if top and top.af2_complex_pdb and Path(top.af2_complex_pdb).exists():
        top_pdb_text = Path(top.af2_complex_pdb).read_text(
            encoding="utf-8", errors="replace"
        )

    pipeline = _compute_pipeline_counts(triage)

    body = _PAGE.format(
        title=html.escape(f"proteinclaw run {run_id}"),
        molstar_js=_MOLSTAR_JS,
        molstar_css=_MOLSTAR_CSS,
        css=_CSS,
        topbar=_render_topbar(triage, run_id=run_id, meta=meta),
        prompt=html.escape(prompt),
        hero=_render_hero(triage, top, meta),
        pipeline=_render_pipeline(pipeline),
        ranked_grid=_render_design_grid(triage, meta),
        scatter=_render_scatter(triage),
        viewer=_render_viewer(top, top_pdb_text),
        notes=_render_notes(triage),
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# pipeline / aggregate stats
# ---------------------------------------------------------------------------


def _compute_pipeline_counts(triage: TriageResult) -> dict[str, int]:
    """Count designs at each stage of the cascade from the triage records."""
    # Unique RFD3 backbones = unique source.mpnn_backbone strings.
    rfd3_backbones = {
        d.source.get("mpnn_backbone")
        for d in triage.designs
        if d.source.get("mpnn_backbone")
    }
    mpnn_sequences = len(triage.designs)
    esm_with_score = sum(1 for d in triage.designs if d.esm_monomer_plddt is not None)
    af2_ranked = len(triage.ranked_designs)
    af2_attempted = sum(
        1
        for d in triage.designs
        if d.af2_complex_plddt is not None or d in triage.unranked_designs
    )
    return {
        "rfd3_backbones": len(rfd3_backbones) or "?",  # type: ignore[dict-item]
        "mpnn_sequences": mpnn_sequences,
        "esm_predictions": esm_with_score,
        "af2_attempted": af2_attempted,
        "af2_ranked": af2_ranked,
    }


# ---------------------------------------------------------------------------
# section renderers
# ---------------------------------------------------------------------------


def _render_topbar(
    triage: TriageResult, *, run_id: str, meta: dict[str, Any]
) -> str:
    target = triage.target
    title_part = f' — {html.escape(target.title)}' if target.title else ''
    target_summary = (
        f'PDB <code>{html.escape(target.pdb_id or "?")}</code>'
        f' chain <code>{html.escape(target.chain or "?")}</code>'
        f' crop <code>{html.escape(target.crop or "?")}</code>'
        f'{title_part}'
    )
    cost = meta.get("total_cost_usd")
    elapsed = meta.get("elapsed_s")
    pills = [
        f'<span class="pill">target: {target_summary}</span>',
        f'<span class="pill"><b>{len(triage.ranked_designs)}</b> ranked'
        + (f' / {len(triage.designs)} total' if len(triage.designs) > len(triage.ranked_designs) else '')
        + '</span>',
    ]
    if elapsed is not None:
        pills.append(f'<span class="pill">elapsed: <b>{elapsed:.1f}s</b></span>')
    if cost is not None:
        pills.append(f'<span class="pill">cost: <b>${cost:.3f}</b></span>')

    return f'''
<header class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <span class="brand-name">proteinclaw</span>
      <span class="brand-sub">design report</span>
    </div>
    <div class="run-meta">
      <span class="pill mono">run {html.escape(run_id)}</span>
      {''.join(pills)}
    </div>
  </div>
</header>
'''


def _render_hero(
    triage: TriageResult, top: Optional[DesignRecord], meta: dict[str, Any]
) -> str:
    if top is None:
        return '''
<section class="hero hero-empty">
  <p><strong>No AF2-ranked designs.</strong> The agent did not produce a
  complete pipeline run; see the notes section for diagnostics.</p>
</section>
'''
    af2 = top.af2_complex_plddt or 0.0
    esm = top.esm_monomer_plddt
    badge_class = _plddt_class(af2)
    msa = "DEGRADED" if top.msa_degraded else "MSA OK"
    msa_class = "warn" if top.msa_degraded else "ok"
    return f'''
<section class="hero">
  <div class="hero-rank">
    <div class="rank-badge gold">#1</div>
    <div class="rank-label">Top binder</div>
  </div>
  <div class="hero-metric">
    <div class="big-number {badge_class}">{af2:.1f}</div>
    <div class="big-label">AF2 complex pLDDT<br><span class="muted">(higher = better)</span></div>
  </div>
  <div class="hero-aux">
    <div class="aux-row"><span class="aux-label">ESM monomer</span><span class="aux-value">{(f"{esm:.1f}" if esm is not None else "—")}</span></div>
    <div class="aux-row"><span class="aux-label">length</span><span class="aux-value">{top.binder_length} aa</span></div>
    <div class="aux-row"><span class="aux-label">MSA</span><span class="aux-value badge-{msa_class}">{msa}</span></div>
  </div>
</section>
'''


def _render_pipeline(counts: dict[str, Any]) -> str:
    steps = [
        ("RFdiffusion3", str(counts["rfd3_backbones"]), "backbones"),
        ("ProteinMPNN", str(counts["mpnn_sequences"]), "sequences"),
        ("ESMFold", str(counts["esm_predictions"]), "predictions"),
        ("AF2-multimer", str(counts["af2_ranked"]), "ranked"),
    ]
    parts = ['<section class="pipeline"><h2>Pipeline</h2><div class="pipeline-row">']
    for i, (name, count, label) in enumerate(steps):
        if i > 0:
            parts.append('<div class="pipe-arrow">→</div>')
        parts.append(
            f'<div class="pipe-step">'
            f'<div class="pipe-count">{html.escape(count)}</div>'
            f'<div class="pipe-name">{html.escape(name)}</div>'
            f'<div class="pipe-sub">{html.escape(label)}</div>'
            f'</div>'
        )
    parts.append('</div></section>')
    return "".join(parts)


def _render_design_grid(triage: TriageResult, meta: dict[str, Any]) -> str:
    cards = []
    for d in triage.ranked_designs:
        cards.append(_render_design_card(d))
    if triage.unranked_designs:
        cards.append(
            f'<div class="unranked-banner">'
            f'<strong>{len(triage.unranked_designs)} design(s)</strong> '
            f'filtered out (ESM below threshold or AF2 failed). Listed below for diagnostics.'
            f'</div>'
        )
        for d in triage.unranked_designs:
            cards.append(_render_design_card(d, unranked=True))
    if not cards:
        return '<section class="ranked-section"><h2>Ranked designs</h2><p class="muted">No designs found in the trace.</p></section>'
    threshold = (
        f'  <span class="muted">(ESMFold threshold the agent used: '
        f'<b>{triage.esm_threshold_used}</b>)</span>'
        if triage.esm_threshold_used is not None
        else ""
    )
    return (
        '<section class="ranked-section">'
        f'<h2>Ranked designs{threshold}</h2>'
        '<div class="design-grid">'
        + "".join(cards)
        + '</div></section>'
    )


def _render_design_card(d: DesignRecord, *, unranked: bool = False) -> str:
    af2 = d.af2_complex_plddt
    esm = d.esm_monomer_plddt
    af2_class = _plddt_class(af2) if af2 is not None else "neutral"
    esm_class = _plddt_class(esm) if esm is not None else "neutral"
    rank_html = (
        f'<div class="rank-badge {_rank_class(d.rank)}">#{d.rank}</div>'
        if d.rank is not None
        else '<div class="rank-badge muted">—</div>'
    )
    msa_pill = (
        '<span class="badge badge-warn">MSA DEGRADED</span>'
        if d.msa_degraded
        else ('<span class="badge badge-ok">MSA OK</span>' if af2 is not None else '')
    )
    af2_html = (
        f'<div class="metric primary"><span class="m-value {af2_class}">{af2:.1f}</span>'
        f'<span class="m-label">complex pLDDT</span></div>'
        if af2 is not None
        else '<div class="metric primary"><span class="m-value neutral">—</span>'
        '<span class="m-label">complex pLDDT</span></div>'
    )
    esm_html = (
        f'<div class="metric"><span class="m-value {esm_class}">{esm:.1f}</span>'
        f'<span class="m-label">ESM monomer</span></div>'
        if esm is not None
        else '<div class="metric"><span class="m-value neutral">—</span>'
        '<span class="m-label">ESM monomer</span></div>'
    )
    len_html = (
        f'<div class="metric"><span class="m-value">{d.binder_length}</span>'
        f'<span class="m-label">length (aa)</span></div>'
    )

    seq_clean = (d.sequence or "").replace("/", "")
    per_res = _render_per_residue_bar(d)
    seq_text = _render_sequence_text(seq_clean)
    pdb_link = (
        f'<a class="btn" href="{html.escape(d.af2_complex_pdb)}">⬇ complex PDB</a>'
        if d.af2_complex_pdb
        else ''
    )
    return f'''
<article class="design-card{' unranked' if unranked else ''}">
  <header class="card-head">
    {rank_html}
    <div class="card-id">design</div>
    {msa_pill}
  </header>
  <div class="metrics">
    {af2_html}
    {esm_html}
    {len_html}
  </div>
  {per_res}
  {seq_text}
  <footer class="card-foot">{pdb_link}</footer>
</article>
'''


def _render_per_residue_bar(d: DesignRecord) -> str:
    """Per-residue pLDDT colored bar from ESMFold per_residue_plddt.

    If the per-residue list isn't present (e.g. only AF2 ran), fall back
    to a single-color bar at the monomer mean.
    """
    # DesignRecord doesn't carry per_residue_plddt today; we read it from
    # the ESM envelope via triage's stored field if available. For now we
    # render a single-cell-per-residue colored by the monomer-level pLDDT
    # because that's what triage gives us. If a future triage change
    # surfaces per_residue_plddt, this function takes over.
    per_residue = getattr(d, "per_residue_plddt", None)
    if per_residue and isinstance(per_residue, list) and per_residue:
        cells = "".join(
            f'<span class="cell {_plddt_class(v)}" title="res {i+1}: {v:.1f}"></span>'
            for i, v in enumerate(per_residue)
        )
        return (
            '<div class="per-residue">'
            '<div class="per-residue-label">per-residue pLDDT</div>'
            f'<div class="per-residue-cells">{cells}</div>'
            '</div>'
        )
    # Fallback: synthesize from the monomer pLDDT (single colour).
    if d.esm_monomer_plddt is not None:
        n = d.binder_length or len(d.sequence or "")
        if n > 0:
            cls = _plddt_class(d.esm_monomer_plddt)
            cells = f'<span class="cell {cls}" title="mean pLDDT (per-residue not surfaced): {d.esm_monomer_plddt:.1f}"></span>' * n
            return (
                '<div class="per-residue">'
                '<div class="per-residue-label">pLDDT band (mean)</div>'
                f'<div class="per-residue-cells">{cells}</div>'
                '</div>'
            )
    return ""


def _render_sequence_text(seq: str) -> str:
    if not seq:
        return ""
    # Break the sequence into 10-aa groups with monospace styling.
    chunks = [seq[i:i+10] for i in range(0, len(seq), 10)]
    body = " ".join(chunks)
    return (
        '<div class="sequence-block">'
        f'<div class="seq-label">sequence ({len(seq)} aa)</div>'
        f'<code class="seq-text">{html.escape(body)}</code>'
        '</div>'
    )


def _plddt_class(v: Optional[float]) -> str:
    if v is None:
        return "neutral"
    if v >= 80:
        return "very-high"
    if v >= 70:
        return "high"
    if v >= 50:
        return "mid"
    return "low"


def _rank_class(rank: Optional[int]) -> str:
    if rank == 1:
        return "gold"
    if rank == 2:
        return "silver"
    if rank == 3:
        return "bronze"
    return "neutral"


def _render_scatter(triage: TriageResult) -> str:
    pts = [
        d for d in triage.designs
        if d.esm_monomer_plddt is not None and d.af2_complex_plddt is not None
    ]
    if not pts:
        return (
            '<section><h2>Folds vs docks</h2>'
            '<p class="muted">No designs with both ESM and AF2 pLDDT to plot.</p>'
            '</section>'
        )

    W, H, P = 560, 380, 50
    def sx(v: float) -> float:
        return P + (v / 100.0) * (W - P - 30)
    def sy(v: float) -> float:
        return H - P - (v / 100.0) * (H - 2 * P)

    parts = [
        '<section class="scatter-section"><h2>Folds vs docks</h2>',
        '<p class="caption">Designs in the upper-right quadrant fold AND dock — '
        'rank these. Designs in the lower-right fold but don\'t dock; promoting '
        'these is the classic monomer-pLDDT mistake the cascade is designed to '
        'prevent. Red dots = MSA-degraded AF2.</p>',
        f'<svg viewBox="0 0 {W} {H}" class="scatter" xmlns="http://www.w3.org/2000/svg" role="img">',
        # Plot area + "good zone" tinted box.
        f'<rect x="{sx(70)}" y="{sy(100)}" width="{sx(100)-sx(70)}" height="{sy(70)-sy(100)}" '
        'fill="#dcfce7" opacity="0.6"/>',
        # Plot frame.
        f'<rect x="{P}" y="{P}" width="{W-P-30}" height="{H-2*P}" fill="none" '
        'stroke="#cbd5e1"/>',
        # Diagonal reference (perfect ESM=AF2 correlation).
        f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(100)}" y2="{sy(100)}" '
        'stroke="#cbd5e1" stroke-dasharray="3 3"/>',
        # Tick lines at 50 and 70.
        f'<line x1="{sx(50)}" y1="{P}" x2="{sx(50)}" y2="{H-P}" stroke="#f1f5f9"/>',
        f'<line x1="{sx(70)}" y1="{P}" x2="{sx(70)}" y2="{H-P}" stroke="#cbd5e1"/>',
        f'<line x1="{P}" y1="{sy(50)}" x2="{W-30}" y2="{sy(50)}" stroke="#f1f5f9"/>',
        f'<line x1="{P}" y1="{sy(70)}" x2="{W-30}" y2="{sy(70)}" stroke="#cbd5e1"/>',
        # Tick labels.
        f'<text x="{sx(50)}" y="{H-P+18}" text-anchor="middle" class="tk">50</text>',
        f'<text x="{sx(70)}" y="{H-P+18}" text-anchor="middle" class="tk">70</text>',
        f'<text x="{sx(100)}" y="{H-P+18}" text-anchor="middle" class="tk">100</text>',
        f'<text x="{P-8}" y="{sy(50)+3}" text-anchor="end" class="tk">50</text>',
        f'<text x="{P-8}" y="{sy(70)+3}" text-anchor="end" class="tk">70</text>',
        f'<text x="{P-8}" y="{sy(100)+3}" text-anchor="end" class="tk">100</text>',
        # Axis labels.
        f'<text x="{W/2}" y="{H-12}" text-anchor="middle" class="ax">ESM monomer pLDDT</text>',
        f'<text x="14" y="{H/2}" text-anchor="middle" '
        f'transform="rotate(-90 14 {H/2})" class="ax">AF2 complex pLDDT (THE ranking signal)</text>',
        # Zone label.
        f'<text x="{sx(85)}" y="{sy(95)}" class="zone">folds &amp; docks</text>',
    ]
    for d in pts:
        color = "#dc2626" if d.msa_degraded else "#2563eb"
        cx, cy = sx(d.esm_monomer_plddt), sy(d.af2_complex_plddt)
        rank_label = f" rank={d.rank}" if d.rank is not None else ""
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{color}" '
            f'fill-opacity="0.75" stroke="#0f172a" stroke-width="0.7">'
            f'<title>esm={d.esm_monomer_plddt:.1f}  af2={d.af2_complex_plddt:.1f}{rank_label}\n'
            f'seq={html.escape(d.sequence[:30])}…</title></circle>'
        )
        if d.rank is not None:
            parts.append(
                f'<text x="{cx+10:.1f}" y="{cy+4:.1f}" class="dot-label">#{d.rank}</text>'
            )
    parts.append('</svg></section>')
    return "".join(parts)


def _render_viewer(top: Optional[DesignRecord], pdb_text: str) -> str:
    if top is None or not pdb_text:
        return (
            '<section><h2>Top design structure</h2>'
            '<p class="muted">No structure to render — top design has no AF2 PDB on disk.</p>'
            '</section>'
        )
    pdb_js = json.dumps(pdb_text)
    return f'''
<section class="viewer-section">
  <h2>Top design structure</h2>
  <p class="caption">Rank-1 binder + target complex (AF2-multimer prediction).
     Use Mol′'s mouse controls to rotate / zoom; sequence + per-residue
     pLDDT details are above.</p>
  <div id="molstar-viewer" class="viewer"></div>
  <script>const TOP_PDB={pdb_js};
function _bootViewer() {{
  if (typeof molstar === "undefined" || !molstar.Viewer) {{ setTimeout(_bootViewer, 200); return; }}
  molstar.Viewer.create("molstar-viewer", {{
    layoutIsExpanded: false,
    layoutShowControls: true,
    viewportShowExpand: true,
    viewportShowSelectionMode: false,
    pdbProvider: "rcsb", emdbProvider: "rcsb",
  }}).then(v => v.loadStructureFromData(TOP_PDB, "pdb"))
    .catch(e => {{
      document.getElementById("molstar-viewer").innerHTML =
        "<p>Mol′ failed to load: " + e + ". The PDB is on disk; open it in PyMOL/ChimeraX.</p>";
    }});
}}
_bootViewer();</script>
</section>
'''


def _render_notes(triage: TriageResult) -> str:
    if not triage.notes:
        return ""
    items = "".join(f"<li>{html.escape(n)}</li>" for n in triage.notes)
    return f'<section><h2>Notes</h2><ul class="notes">{items}</ul></section>'


# ---------------------------------------------------------------------------
# CSS + page template
# ---------------------------------------------------------------------------


_CSS = """
*, *::before, *::after { box-sizing: border-box; }
:root {
  --fg: #0f172a; --fg-muted: #64748b; --fg-dim: #94a3b8;
  --bg: #ffffff; --bg-soft: #f8fafc; --bg-card: #ffffff;
  --border: #e2e8f0; --border-strong: #cbd5e1;
  --accent: #2563eb;
  --gold: #ca8a04; --gold-bg: #fef3c7;
  --silver: #6b7280; --silver-bg: #e5e7eb;
  --bronze: #b45309; --bronze-bg: #fde68a;
  --green: #16a34a; --green-bg: #dcfce7;
  --amber: #d97706; --amber-bg: #fef3c7;
  --red: #dc2626; --red-bg: #fee2e2;
}
html, body { margin: 0; padding: 0; background: var(--bg-soft); color: var(--fg);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif; }
code, .mono { font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.muted { color: var(--fg-muted); }

/* Top bar */
.topbar { position: sticky; top: 0; z-index: 10; background: var(--bg); border-bottom: 1px solid var(--border);
  padding: 14px 24px; box-shadow: 0 1px 0 rgba(0,0,0,0.02); }
.topbar-inner { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
.brand-name { font-weight: 700; font-size: 19px; color: var(--accent); margin-right: 6px; }
.brand-sub { color: var(--fg-muted); font-size: 14px; }
.run-meta { display: flex; gap: 8px; flex-wrap: wrap; }
.pill { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 999px;
  padding: 4px 12px; font-size: 13px; color: var(--fg); }
.pill code { background: transparent; padding: 0; color: var(--fg); }
.pill b { color: var(--fg); }

main { max-width: 1200px; margin: 0 auto; padding: 24px; }
section { margin-bottom: 32px; }
h2 { font-size: 18px; margin: 0 0 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); font-weight: 600; }
.caption { color: var(--fg-muted); font-size: 14px; margin: -8px 0 16px; }

/* Prompt block */
.prompt-block { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; margin-bottom: 24px; font-size: 14px; color: var(--fg-muted); }
.prompt-block strong { color: var(--fg); }

/* Hero card */
.hero { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px; display: grid; grid-template-columns: auto 1fr auto; gap: 32px; align-items: center;
  margin-bottom: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.hero-rank { text-align: center; }
.hero .rank-badge { font-size: 22px; padding: 8px 16px; }
.rank-label { font-size: 13px; color: var(--fg-muted); margin-top: 6px; }
.hero-metric { text-align: center; }
.big-number { font-size: 72px; font-weight: 700; line-height: 1; }
.big-label { font-size: 14px; color: var(--fg-muted); margin-top: 6px; }
.hero-aux { min-width: 220px; }
.aux-row { display: flex; justify-content: space-between; padding: 6px 0; font-size: 14px;
  border-bottom: 1px solid var(--border); }
.aux-row:last-child { border-bottom: none; }
.aux-label { color: var(--fg-muted); }
.aux-value { font-weight: 600; }
.hero-empty { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 24px; }

/* Rank badges */
.rank-badge { display: inline-block; font-weight: 700; border-radius: 8px; padding: 4px 10px; font-size: 14px; }
.rank-badge.gold   { background: var(--gold-bg);   color: var(--gold); }
.rank-badge.silver { background: var(--silver-bg); color: var(--silver); }
.rank-badge.bronze { background: var(--bronze-bg); color: var(--bronze); }
.rank-badge.neutral, .rank-badge.muted { background: var(--bg-soft); color: var(--fg-muted); }

/* pLDDT colour classes */
.very-high { color: var(--green); }
.high      { color: #65a30d; }
.mid       { color: var(--amber); }
.low       { color: var(--red); }
.neutral   { color: var(--fg-muted); }

/* Pipeline strip */
.pipeline-row { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.pipe-step { flex: 1; text-align: center; }
.pipe-count { font-size: 32px; font-weight: 700; color: var(--accent); line-height: 1; }
.pipe-name  { font-size: 14px; font-weight: 600; margin-top: 6px; }
.pipe-sub   { font-size: 12px; color: var(--fg-muted); }
.pipe-arrow { font-size: 24px; color: var(--fg-dim); }

/* Design grid */
.design-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
.design-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px; display: flex; flex-direction: column; gap: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
.design-card.unranked { opacity: 0.7; }
.card-head { display: flex; align-items: center; gap: 10px; }
.card-id { flex: 1; font-size: 14px; color: var(--fg-muted); }

/* Badges in cards */
.badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px; }
.badge-ok    { background: var(--green-bg); color: var(--green); }
.badge-warn  { background: var(--red-bg);   color: var(--red); }

/* Card metrics */
.metrics { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 8px; }
.metric { background: var(--bg-soft); border-radius: 8px; padding: 10px 12px; }
.metric .m-value { display: block; font-size: 22px; font-weight: 700; line-height: 1; }
.metric .m-label { display: block; font-size: 11px; color: var(--fg-muted); margin-top: 4px; }
.metric.primary  { background: #eff6ff; border: 1px solid #dbeafe; }
.metric.primary .m-value { font-size: 28px; }

/* Per-residue pLDDT bar */
.per-residue { }
.per-residue-label { font-size: 12px; color: var(--fg-muted); margin-bottom: 4px; }
.per-residue-cells { display: flex; gap: 1px; height: 14px; overflow: hidden; border-radius: 2px;
  border: 1px solid var(--border); }
.cell { flex: 1; min-width: 0; }
.cell.very-high { background: var(--green); }
.cell.high      { background: #84cc16; }
.cell.mid       { background: var(--amber); }
.cell.low       { background: var(--red); }
.cell.neutral   { background: var(--fg-dim); }

/* Sequence */
.sequence-block { background: var(--bg-soft); border-radius: 8px; padding: 10px 12px; }
.seq-label { font-size: 11px; color: var(--fg-muted); margin-bottom: 4px; }
.seq-text  { display: block; word-wrap: break-word; word-break: break-all; }

/* Card footer */
.card-foot { display: flex; gap: 8px; }
.btn { display: inline-block; padding: 6px 12px; background: var(--bg-soft); border: 1px solid var(--border);
  border-radius: 6px; color: var(--fg); text-decoration: none; font-size: 13px; font-weight: 500; }
.btn:hover { background: var(--bg); border-color: var(--border-strong); }

/* Unranked banner */
.unranked-banner { grid-column: 1 / -1; background: #fffbeb; border: 1px solid #fde68a;
  border-radius: 8px; padding: 12px 16px; color: #92400e; font-size: 14px; }

/* Scatter */
.scatter-section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.scatter { display: block; max-width: 100%; height: auto; margin: 0 auto; }
.ax     { font-size: 12px; fill: var(--fg-muted); font-weight: 500; }
.tk     { font-size: 11px; fill: var(--fg-dim); }
.zone   { font-size: 12px; fill: var(--green); font-weight: 600; }
.dot-label { font-size: 11px; fill: var(--fg); font-weight: 600; }

/* Mol* viewer */
.viewer-section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.viewer { width: 100%; height: 540px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  background: var(--bg-soft); }

/* Notes */
.notes { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 24px; list-style: disc; }
.notes li { margin: 4px 0; }

/* Footer */
footer.page-foot { max-width: 1200px; margin: 32px auto; padding: 16px 24px; color: var(--fg-dim);
  font-size: 12px; text-align: center; border-top: 1px solid var(--border); }
footer.page-foot a { color: var(--fg-muted); }

@media (max-width: 720px) {
  .hero { grid-template-columns: 1fr; text-align: center; }
  .big-number { font-size: 56px; }
  .metrics { grid-template-columns: 1fr; }
  .pipeline-row { flex-direction: column; }
  .pipe-arrow { transform: rotate(90deg); }
}
"""


_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <link rel="stylesheet" href="{molstar_css}">
  <script src="{molstar_js}"></script>
  <style>{css}</style>
</head>
<body>
  {topbar}
  <main>
    <div class="prompt-block"><strong>Prompt:</strong> {prompt}</div>
    {hero}
    {pipeline}
    {ranked_grid}
    {scatter}
    {viewer}
    {notes}
  </main>
  <footer class="page-foot">
    Generated by <code>proteinclaw</code>. Ranking signal: AF2-multimer
    complex pLDDT averaged over the binder chain (PRD §6.6).
    Structure view by <a href="https://molstar.org">Mol′</a>.
  </footer>
</body>
</html>
"""


__all__ = ["render_report"]

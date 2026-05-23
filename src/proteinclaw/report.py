"""Single-file ``report.html`` renderer.

Inputs: a ``TriageResult`` (from ``agent/triage.py``). Outputs: a self-
contained HTML file with:
  * Header (target chosen, ranking signal, run summary)
  * Rank table (rank, pLDDTs, sequence preview, design PDB link)
  * ESM-vs-AF2 scatter (inline SVG; identifies designs that fold but
    don't dock)
  * Top design in Mol* viewer (loaded from a CDN; PDB text inlined into
    the HTML so no separate file fetch is needed)

External deps: Mol* viewer + CSS via cdn.jsdelivr.net. Page works
offline AFTER first load (browser cache). For fully air-gapped use,
download Mol* once and inline.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from proteinclaw.agent.triage import DesignRecord, TriageResult


_MOLSTAR_JS = "https://cdn.jsdelivr.net/npm/molstar@latest/build/viewer/molstar.js"
_MOLSTAR_CSS = "https://cdn.jsdelivr.net/npm/molstar@latest/build/viewer/molstar.css"


def render_report(
    triage: TriageResult,
    *,
    run_id: str,
    prompt: str,
    output_path: Path,
    extra_meta: dict[str, Any] | None = None,
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

    html_out = _PAGE.format(
        title=html.escape(f"proteinclaw run {run_id}"),
        molstar_js=_MOLSTAR_JS,
        molstar_css=_MOLSTAR_CSS,
        header=_render_header(triage, run_id=run_id, prompt=prompt, meta=meta),
        rank_table=_render_rank_table(triage),
        scatter_svg=_render_scatter(triage),
        top_section=_render_top_section(top, top_pdb_text),
        notes=_render_notes(triage),
    )
    output_path.write_text(html_out, encoding="utf-8")
    return output_path


def _render_header(
    triage: TriageResult,
    *,
    run_id: str,
    prompt: str,
    meta: dict[str, Any],
) -> str:
    target = triage.target
    cost = meta.get("total_cost_usd")
    elapsed = meta.get("elapsed_s")
    parts = [
        f'<div class="kv"><span>run_id</span><code>{html.escape(run_id)}</code></div>',
        f'<div class="kv"><span>prompt</span><span>{html.escape(prompt)}</span></div>',
        f'<div class="kv"><span>target</span><span>'
        f'PDB <code>{html.escape(target.pdb_id or "?")}</code> '
        f'chain <code>{html.escape(target.chain or "?")}</code> '
        f'crop <code>{html.escape(target.crop or "?")}</code></span></div>',
        f'<div class="kv"><span>title</span><span>{html.escape(target.title or "?")}</span></div>',
        f'<div class="kv"><span>ranking signal</span><span>'
        f'{html.escape(triage.ranking_signal)} (higher = better)</span></div>',
        f'<div class="kv"><span>esm threshold used</span><span>'
        f'{triage.esm_threshold_used if triage.esm_threshold_used is not None else "(not detected)"}'
        f'</span></div>',
        f'<div class="kv"><span>designs ranked</span><span>'
        f'{len(triage.ranked_designs)} of {len(triage.designs)} '
        f'({len(triage.unranked_designs)} without AF2 result)</span></div>',
    ]
    if cost is not None:
        parts.append(
            f'<div class="kv"><span>total cost (USD)</span><span>{cost:.3f}</span></div>'
        )
    if elapsed is not None:
        parts.append(
            f'<div class="kv"><span>elapsed</span><span>{elapsed:.1f}s</span></div>'
        )
    return "\n".join(parts)


def _render_rank_table(triage: TriageResult) -> str:
    rows = []
    rows.append(
        '<tr><th>rank</th><th>complex pLDDT</th><th>monomer pLDDT</th>'
        '<th>length</th><th>MSA</th><th>sequence (first 40 aa)</th>'
        '<th>complex PDB</th></tr>'
    )
    for d in triage.ranked_designs:
        msa_cell = (
            '<span class="warn">DEGRADED</span>' if d.msa_degraded else "ok"
        )
        seq_preview = html.escape((d.sequence or "")[:40] + ("…" if len(d.sequence) > 40 else ""))
        af2_cell = (
            f'<span class="big">{d.af2_complex_plddt:.1f}</span>'
            if d.af2_complex_plddt is not None
            else "-"
        )
        esm_cell = (
            f"{d.esm_monomer_plddt:.1f}" if d.esm_monomer_plddt is not None else "-"
        )
        pdb_cell = (
            f'<a href="{html.escape(d.af2_complex_pdb)}">{html.escape(Path(d.af2_complex_pdb).name)}</a>'
            if d.af2_complex_pdb
            else "-"
        )
        rows.append(
            f"<tr><td>{d.rank}</td><td>{af2_cell}</td><td>{esm_cell}</td>"
            f"<td>{d.binder_length}</td><td>{msa_cell}</td>"
            f"<td><code>{seq_preview}</code></td><td>{pdb_cell}</td></tr>"
        )
    if not triage.ranked_designs:
        rows.append('<tr><td colspan="7"><em>no AF2-ranked designs</em></td></tr>')

    if triage.unranked_designs:
        rows.append(
            f'<tr><td colspan="7" class="section">'
            f'{len(triage.unranked_designs)} unranked designs (no AF2 result):'
            f'</td></tr>'
        )
        for d in triage.unranked_designs:
            esm_cell = (
                f"{d.esm_monomer_plddt:.1f}" if d.esm_monomer_plddt is not None else "-"
            )
            seq_preview = html.escape((d.sequence or "")[:40] + ("…" if len(d.sequence) > 40 else ""))
            rows.append(
                f'<tr><td>-</td><td>-</td><td>{esm_cell}</td>'
                f"<td>{d.binder_length}</td><td>-</td>"
                f"<td><code>{seq_preview}</code></td><td>-</td></tr>"
            )
    return "<table class='rank'>" + "".join(rows) + "</table>"


def _render_scatter(triage: TriageResult) -> str:
    """Tiny inline SVG: x = ESM monomer pLDDT, y = AF2 complex pLDDT.

    Designs that fold (high x) but don't dock (low y) cluster in the
    bottom-right and are the classic "monomer-good, complex-bad" case
    the agent should NOT have promoted.
    """
    pts = [
        d for d in triage.designs
        if d.esm_monomer_plddt is not None and d.af2_complex_plddt is not None
    ]
    if not pts:
        return '<p class="muted">(no designs with both ESM and AF2 pLDDT to plot)</p>'

    # Plot canvas — 0..100 on both axes; pad 30 px for labels.
    W, H, P = 480, 360, 36
    def sx(v: float) -> float:
        return P + (v / 100.0) * (W - 2 * P)
    def sy(v: float) -> float:
        return H - P - (v / 100.0) * (H - 2 * P)

    parts = [
        f'<svg viewBox="0 0 {W} {H}" class="scatter" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{P}" y="{P}" width="{W-2*P}" height="{H-2*P}" '
        'fill="none" stroke="#888"/>',
        # Diagonal "perfect correlation" reference line.
        f'<line x1="{sx(0)}" y1="{sy(0)}" x2="{sx(100)}" y2="{sy(100)}" '
        'stroke="#ddd" stroke-dasharray="3 3"/>',
        # Axis labels.
        f'<text x="{W/2}" y="{H-8}" text-anchor="middle" class="ax">'
        'ESM monomer pLDDT (0-100)</text>',
        f'<text x="14" y="{H/2}" text-anchor="middle" '
        f'transform="rotate(-90 14 {H/2})" class="ax">'
        'AF2 complex pLDDT (0-100) — RANKING SIGNAL</text>',
        # Tick labels at 50.
        f'<line x1="{sx(50)}" y1="{P}" x2="{sx(50)}" y2="{H-P}" '
        'stroke="#eee"/>',
        f'<line x1="{P}" y1="{sy(50)}" x2="{W-P}" y2="{sy(50)}" '
        'stroke="#eee"/>',
        f'<text x="{sx(50)}" y="{H-P+14}" text-anchor="middle" class="tk">50</text>',
        f'<text x="{P-6}" y="{sy(50)+3}" text-anchor="end" class="tk">50</text>',
    ]

    for d in pts:
        color = "#d9534f" if d.msa_degraded else "#1f77b4"
        cx, cy = sx(d.esm_monomer_plddt), sy(d.af2_complex_plddt)
        rank_label = f" rank={d.rank}" if d.rank is not None else ""
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{color}" '
            f'fill-opacity="0.7" stroke="#222" stroke-width="0.5">'
            f'<title>esm={d.esm_monomer_plddt:.1f} '
            f'af2={d.af2_complex_plddt:.1f}{rank_label}'
            f' seq={d.sequence[:20]}</title></circle>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _render_top_section(top: DesignRecord | None, pdb_text: str) -> str:
    if top is None:
        return '<p class="muted">(no top design — no AF2-ranked results)</p>'
    if not pdb_text:
        return (
            f'<p class="muted">Top design rank 1 (complex pLDDT '
            f'{top.af2_complex_plddt:.1f}) at <code>'
            f'{html.escape(top.af2_complex_pdb or "?")}</code> — '
            'no PDB text inlined (file missing or unreadable).</p>'
        )
    # Inline the PDB text into a JS variable. Mol* loads from string via
    # `loadStructureFromData(data, 'pdb')`.
    pdb_js = json.dumps(pdb_text)
    return (
        f'<p>Top design rank 1, complex pLDDT '
        f'<span class="big">{top.af2_complex_plddt:.1f}</span>, '
        f'sequence (full): <code>{html.escape(top.sequence)}</code></p>'
        f'<div id="molstar-viewer" style="width:100%;height:520px;'
        'border:1px solid #ddd"></div>'
        f'<script>const TOP_PDB={pdb_js};'
        'function _bootViewer(){'
        '  if (typeof molstar==="undefined" || !molstar.Viewer){setTimeout(_bootViewer,150);return;}'
        '  molstar.Viewer.create("molstar-viewer",{'
        '    layoutIsExpanded:false,layoutShowControls:false,'
        '    viewportShowExpand:true,viewportShowSelectionMode:false,'
        '    pdbProvider:"rcsb",emdbProvider:"rcsb",'
        '  }).then(v=>v.loadStructureFromData(TOP_PDB,"pdb")).catch(e=>{'
        '    document.getElementById("molstar-viewer").innerHTML='
        '      "<p>Mol* failed to load: "+e+". The PDB file is on disk; "+'
        '      "open it in PyMOL / ChimeraX.</p>";'
        '  });'
        '}_bootViewer();</script>'
    )


def _render_notes(triage: TriageResult) -> str:
    if not triage.notes:
        return ""
    items = "".join(f"<li>{html.escape(n)}</li>" for n in triage.notes)
    return f'<h2>Notes</h2><ul class="notes">{items}</ul>'


_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <link rel="stylesheet" href="{molstar_css}">
  <script src="{molstar_js}"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
            "Helvetica Neue", Arial, sans-serif; max-width: 1100px; margin: 24px auto;
            padding: 0 16px; color: #222; }}
    h1 {{ margin: 0 0 4px; }}
    h2 {{ margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    .header .kv {{ display: grid; grid-template-columns: 180px 1fr;
            gap: 8px; padding: 4px 0; border-bottom: 1px solid #f0f0f0; }}
    .header .kv span:first-child {{ color: #666; font-size: 13px; }}
    table.rank {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    table.rank th, table.rank td {{ padding: 6px 10px; text-align: left;
            border-bottom: 1px solid #eee; }}
    table.rank th {{ background: #fafafa; }}
    .big {{ font-weight: 600; font-size: 16px; }}
    .warn {{ color: #d9534f; font-weight: 600; }}
    .muted {{ color: #888; }}
    .ax {{ font-size: 12px; fill: #555; }}
    .tk {{ font-size: 10px; fill: #888; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            background: #f6f6f6; padding: 1px 5px; border-radius: 3px; font-size: 13px; }}
    .section {{ font-weight: 600; background: #fafafa; }}
    svg.scatter {{ display: block; max-width: 100%; height: auto; }}
    .notes li {{ margin-bottom: 4px; }}
  </style>
</head>
<body>
  <h1>proteinclaw — design report</h1>
  <p class="muted">Designs ranked by AF2-multimer complex pLDDT averaged over
     the binder chain (the ranking signal per PRD §6.6). Higher is better.</p>

  <section class="header">{header}</section>

  <h2>Ranked designs</h2>
  {rank_table}

  <h2>ESM monomer pLDDT vs AF2 complex pLDDT</h2>
  <p class="muted">Designs in the upper-right fold and dock. Designs in
     the lower-right fold but don't dock — promoting these is the classic
     monomer-pLDDT mistake the cascade is designed to prevent. Red dots
     are MSA-degraded AF2 runs (lower-confidence).</p>
  {scatter_svg}

  <h2>Top design (Mol*)</h2>
  {top_section}

  {notes}

  <footer style="margin-top:48px;font-size:12px;color:#aaa;border-top:1px solid #eee;padding-top:8px">
    Generated by <code>proteinclaw</code>. PDB rendering by
    <a href="https://molstar.org">Mol*</a> (CDN). To regenerate: open the
    run's <code>result.json</code> in your tooling of choice.
  </footer>
</body>
</html>
"""


__all__ = ["render_report"]

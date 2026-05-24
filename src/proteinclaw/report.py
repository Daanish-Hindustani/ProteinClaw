"""Single-file ``report.html`` renderer — minimal layout.

Four sections, top to bottom:
  1. Metadata bar (run id, target, elapsed, cost, ranked count).
  2. Mol* 3D viewer of the rank-1 AF2 complex.
  3. Candidates list (rank, AF2 / ESM pLDDT, length, sequence, PDB link).
  4. Agent reasoning (assistant text from the trace, in order).

External dep: Mol* via cdn.jsdelivr.net. PDB text is inlined.
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
    designs_dir = output_path.parent / "designs"
    # Resolve a usable PDB path for each ranked design. The record's
    # af2_complex_pdb may point at a GPU-workspace path that doesn't exist
    # on the host viewing the report (e.g. results copied off a remote
    # box); fall back to the locally-staged rank_NN_<id>.pdb if present.
    for d in ranked:
        d.af2_complex_pdb = _resolve_pdb(d, designs_dir)
    top_pdb_text = ""
    if top and top.af2_complex_pdb and Path(top.af2_complex_pdb).exists():
        top_pdb_text = Path(top.af2_complex_pdb).read_text(
            encoding="utf-8", errors="replace"
        )

    body = _PAGE.format(
        title=html.escape(f"proteinclaw run {run_id}"),
        molstar_js=_MOLSTAR_JS,
        molstar_css=_MOLSTAR_CSS,
        css=_CSS,
        metabar=_render_metabar(triage, run_id=run_id, prompt=prompt, meta=meta),
        viewer=_render_viewer(top, top_pdb_text),
        candidates=_render_candidates(triage),
        reasoning=_render_reasoning(meta.get("reasoning") or [], triage.notes),
    )
    output_path.write_text(body, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_pdb(d: DesignRecord, designs_dir: Path) -> Optional[str]:
    """Return a path to the design's PDB that actually exists on disk.

    Order: (1) the recorded af2_complex_pdb if present, (2) the staged
    ``designs/rank_NN_<seq6>.pdb`` filename used by stage_ranked_designs.
    """
    if d.af2_complex_pdb and Path(d.af2_complex_pdb).exists():
        return d.af2_complex_pdb
    if d.rank is not None and d.sequence:
        candidate = designs_dir / f"rank_{d.rank:02d}_{d.sequence[:6]}.pdb"
        if candidate.exists():
            return str(candidate)
    return d.af2_complex_pdb


# ---------------------------------------------------------------------------
# section renderers
# ---------------------------------------------------------------------------


def _render_metabar(
    triage: TriageResult,
    *,
    run_id: str,
    prompt: str,
    meta: dict[str, Any],
) -> str:
    target = triage.target
    target_bits: list[str] = []
    if target.pdb_id:
        target_bits.append(f"PDB <code>{html.escape(target.pdb_id)}</code>")
    if target.chain:
        target_bits.append(f"chain <code>{html.escape(target.chain)}</code>")
    if target.crop:
        target_bits.append(f"crop <code>{html.escape(target.crop)}</code>")
    if target.title:
        target_bits.append(html.escape(target.title))
    target_line = " · ".join(target_bits) or '<span class="muted">target unresolved</span>'

    cost = meta.get("total_cost_usd")
    elapsed = meta.get("elapsed_s")
    turns = meta.get("num_turns")

    stats = [
        ("run", f"<code>{html.escape(run_id)}</code>"),
        ("ranked", f"{len(triage.ranked_designs)} / {len(triage.designs)}"),
    ]
    if elapsed is not None:
        stats.append(("elapsed", f"{elapsed:.1f}s"))
    if turns is not None:
        stats.append(("turns", str(turns)))
    if cost is not None:
        stats.append(("cost", f"${cost:.3f}"))

    stat_html = "".join(
        f'<div class="stat"><span class="stat-label">{html.escape(k)}</span>'
        f'<span class="stat-value">{v}</span></div>'
        for k, v in stats
    )

    return f"""
<header class="metabar">
  <div class="metabar-title">proteinclaw <span class="muted">design report</span></div>
  <div class="metabar-prompt"><span class="muted">prompt:</span> {html.escape(prompt)}</div>
  <div class="metabar-target"><span class="muted">target:</span> {target_line}</div>
  <div class="metabar-stats">{stat_html}</div>
</header>
"""


def _render_viewer(top: Optional[DesignRecord], pdb_text: str) -> str:
    if top is None or not pdb_text:
        return (
            '<section class="card"><h2>Structure</h2>'
            '<p class="muted">No structure to render — no ranked design with an '
            'AF2 PDB on disk.</p></section>'
        )
    pdb_js = json.dumps(pdb_text)
    return f"""
<section class="card viewer-section">
  <h2>Structure — rank #1 complex</h2>
  <div id="molstar-viewer" class="viewer"></div>
  <script>const TOP_PDB={pdb_js};
function _bootViewer() {{
  if (typeof molstar === "undefined" || !molstar.Viewer) {{ setTimeout(_bootViewer, 200); return; }}
  molstar.Viewer.create("molstar-viewer", {{
    layoutIsExpanded: false,
    layoutShowControls: false,
    layoutShowSequence: false,
    layoutShowLog: false,
    layoutShowLeftPanel: false,
    viewportShowExpand: true,
    viewportShowSelectionMode: false,
    viewportShowAnimation: false,
    pdbProvider: "rcsb", emdbProvider: "rcsb",
  }}).then(v => v.loadStructureFromData(TOP_PDB, "pdb"))
    .catch(e => {{
      document.getElementById("molstar-viewer").innerHTML =
        "<p>Mol* failed to load: " + e + ". The PDB is on disk; open it in PyMOL/ChimeraX.</p>";
    }});
}}
_bootViewer();</script>
</section>
"""


def _render_candidates(triage: TriageResult) -> str:
    ranked = triage.ranked_designs
    if not ranked:
        return (
            '<section class="card"><h2>Candidates</h2>'
            '<p class="muted">No ranked designs.</p></section>'
        )
    rows = "".join(_render_row(d) for d in ranked)
    return f"""
<section class="card">
  <h2>Candidates <span class="muted">({len(ranked)} ranked, by AF2 complex pLDDT)</span></h2>
  <table class="candidates">
    <thead>
      <tr>
        <th>#</th>
        <th>AF2 complex pLDDT</th>
        <th>ESM monomer</th>
        <th>len</th>
        <th>sequence</th>
        <th>PDB</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _render_row(d: DesignRecord) -> str:
    af2 = "—" if d.af2_complex_plddt is None else f"{d.af2_complex_plddt:.1f}"
    esm = "—" if d.esm_monomer_plddt is None else f"{d.esm_monomer_plddt:.1f}"
    seq_clean = (d.sequence or "").replace("/", "")
    pdb_link = (
        f'<a href="{html.escape(d.af2_complex_pdb)}">⬇</a>'
        if d.af2_complex_pdb
        else "—"
    )
    msa_warn = ' <span class="warn-tag">MSA degraded</span>' if d.msa_degraded else ""
    return f"""
<tr>
  <td class="rank">{d.rank if d.rank is not None else "—"}</td>
  <td class="num">{af2}{msa_warn}</td>
  <td class="num">{esm}</td>
  <td class="num">{d.binder_length}</td>
  <td class="seq"><code>{html.escape(seq_clean)}</code></td>
  <td class="pdb">{pdb_link}</td>
</tr>
"""


def _render_reasoning(reasoning: list[str], notes: list[str]) -> str:
    blocks: list[str] = []
    for text in reasoning:
        blocks.append(f'<div class="reason-block">{html.escape(text)}</div>')
    notes_html = ""
    if notes:
        items = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
        notes_html = f'<div class="notes-block"><h3>Notes</h3><ul>{items}</ul></div>'
    body = "".join(blocks) or '<p class="muted">No agent narration captured.</p>'
    return f"""
<section class="card">
  <h2>Agent reasoning</h2>
  {body}
  {notes_html}
</section>
"""


# ---------------------------------------------------------------------------
# CSS + page template
# ---------------------------------------------------------------------------


_CSS = """
*, *::before, *::after { box-sizing: border-box; }
:root {
  --fg: #0f172a; --fg-muted: #64748b; --fg-dim: #94a3b8;
  --bg: #f8fafc; --bg-card: #ffffff;
  --border: #e2e8f0; --accent: #2563eb;
  --warn: #b45309; --warn-bg: #fef3c7;
}
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif; }
code { font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.muted { color: var(--fg-muted); }

main { max-width: 1100px; margin: 0 auto; padding: 24px; display: flex;
  flex-direction: column; gap: 20px; }

.card { background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px; }
.card h2 { font-size: 16px; margin: 0 0 14px; font-weight: 600; }
.card h2 .muted { font-weight: 400; font-size: 13px; }

/* Metabar */
.metabar { background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px 20px; display: flex; flex-direction: column; gap: 8px; }
.metabar-title { font-size: 18px; font-weight: 700; color: var(--accent); }
.metabar-prompt, .metabar-target { font-size: 14px; }
.metabar-stats { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 6px;
  padding-top: 10px; border-top: 1px solid var(--border); }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--fg-muted); }
.stat-value { font-size: 14px; font-weight: 600; }
.stat-value code { font-size: 13px; }

/* Viewer — Mol*'s shipped CSS assumes fullscreen and gives its canvas
   100vh, which would overflow our 520px container; constrain it. */
.viewer { position: relative; width: 100%; height: 520px;
  border: 1px solid var(--border); border-radius: 8px;
  overflow: hidden; background: var(--bg); }
.viewer .msp-plugin, .viewer .msp-plugin-content,
.viewer .msp-layout-standard, .viewer .msp-layout-region,
.viewer .msp-layout-main, .viewer .msp-viewport {
  position: absolute !important; inset: 0 !important;
  width: 100% !important; height: 100% !important; }
.viewer canvas { width: 100% !important; height: 100% !important;
  display: block; }

/* Candidates table */
table.candidates { width: 100%; border-collapse: collapse; font-size: 14px; }
table.candidates th, table.candidates td { padding: 8px 10px; text-align: left;
  border-bottom: 1px solid var(--border); vertical-align: top; }
table.candidates th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--fg-muted); font-weight: 600; }
table.candidates td.rank { font-weight: 700; width: 36px; }
table.candidates td.num  { font-variant-numeric: tabular-nums; white-space: nowrap; }
table.candidates td.seq code { word-break: break-all; color: var(--fg); font-size: 12px; }
table.candidates td.pdb a { color: var(--accent); text-decoration: none; }
.warn-tag { display: inline-block; margin-left: 6px; font-size: 11px; font-weight: 600;
  padding: 1px 6px; border-radius: 4px; background: var(--warn-bg); color: var(--warn); }

/* Reasoning */
.reason-block { white-space: pre-wrap; padding: 10px 12px; margin-bottom: 10px;
  background: var(--bg); border-left: 3px solid var(--accent); border-radius: 4px;
  font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-x: auto; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
.reason-block:last-child { margin-bottom: 0; }
.notes-block { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); }
.notes-block h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--fg-muted); margin: 0 0 8px; font-weight: 600; }
.notes-block ul { margin: 0; padding-left: 20px; font-size: 14px; }

@media (max-width: 720px) {
  main { padding: 14px; }
  .viewer { height: 380px; }
  table.candidates td.seq { display: none; }
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
  <main>
    {metabar}
    {viewer}
    {candidates}
    {reasoning}
  </main>
</body>
</html>
"""


__all__ = ["render_report"]

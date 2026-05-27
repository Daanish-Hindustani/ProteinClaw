"""Single-file ``report.html`` renderer — minimal layout.

Two tabs:
  • Design report — metadata bar (run id, target, elapsed, cost, ranked count
    + the best-of-suite metric chips against the hit gate), Mol* 3D viewer of
    the rank-1 AF2 complex, full-metric candidates table, run-activity timeline
    (debate · pipeline · self-evolution), and agent reasoning.
  • Raw trace — every ``trace.jsonl`` event, type-filterable.

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

# Strict combined hit gate (must match skills/proteindesign.md §Quality gate).
# A design is a "hit" only if it clears ALL of these; the metric chips and the
# candidates table colour each cell against its threshold so the gate is legible.
_GATE = {
    "plddt": 85.0,   # af2_complex_plddt  (>)
    "ipsae": 0.6,    # af2_ipsae          (>=)
    "iptm": 0.7,     # af2_iptm           (>=)
    "hotspot": 0.70,  # hotspot_satisfaction (>=)
    "bsa": 700.0,    # interface_bsa (Å²) (>=)
}


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
        activity=_render_activity(meta.get("activity") or [], meta.get("skill_edits") or []),
        plan=_render_plan(meta.get("plan_md") or ""),
        reasoning=_render_reasoning(meta.get("reasoning") or [], triage.notes),
        trace=_render_trace(meta.get("trace_events") or []),
        script=_TAB_JS,
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
  {_render_metric_suite(triage.ranked_designs)}
</header>
"""


def _best(values: list[Optional[float]], *, lower_is_better: bool = False) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return min(vals) if lower_is_better else max(vals)


def _is_hit(d: DesignRecord) -> bool:
    """A design clears the strict combined hit gate (all thresholds, §Quality
    gate). Any missing metric fails the gate (can't confirm → not a hit)."""
    return (
        d.af2_complex_plddt is not None and d.af2_complex_plddt > _GATE["plddt"]
        and d.af2_ipsae is not None and d.af2_ipsae >= _GATE["ipsae"]
        and d.af2_iptm is not None and d.af2_iptm >= _GATE["iptm"]
        and d.hotspot_satisfaction is not None and d.hotspot_satisfaction >= _GATE["hotspot"]
        and d.interface_bsa is not None and d.interface_bsa >= _GATE["bsa"]
    )


def _render_metric_suite(ranked: list[DesignRecord]) -> str:
    """Best-of-suite metric chips shown in the metabar — every metric the
    pipeline produces, with the strict hit-gate threshold colour-coded so the
    gate is legible at a glance. ``hits`` counts designs clearing ALL gates."""
    if not ranked:
        return ""
    n = len(ranked)
    hits = sum(1 for d in ranked if _is_hit(d))

    def chip(label: str, best: Optional[float], fmt: str, thr: Optional[float],
             *, ge: bool = True, lower: bool = False) -> str:
        if best is None:
            val, cls = "—", "muted"
        else:
            val = format(best, fmt)
            if thr is None:
                cls = ""
            else:
                ok = (best <= thr if lower else (best >= thr if ge else best > thr))
                cls = "metric-ok" if ok else "metric-bad"
        sub = f" / {format(thr, fmt)}" if thr is not None else ""
        return (
            f'<div class="metric {cls}"><span class="metric-label">{html.escape(label)}</span>'
            f'<span class="metric-value">{val}<span class="metric-thr">{html.escape(sub)}</span>'
            "</span></div>"
        )

    chips = [
        f'<div class="metric {"metric-ok" if hits else "metric-bad"}">'
        f'<span class="metric-label">hits / {n}</span>'
        f'<span class="metric-value">{hits}</span></div>',
        chip("best pLDDT", _best([d.af2_complex_plddt for d in ranked]), ".1f", _GATE["plddt"], ge=False),
        chip("best ipSAE", _best([d.af2_ipsae for d in ranked]), ".3f", _GATE["ipsae"]),
        chip("best ipTM", _best([d.af2_iptm for d in ranked]), ".3f", _GATE["iptm"]),
        chip("best pDockQ", _best([d.af2_pdockq for d in ranked]), ".3f", None),
        chip("best pDockQ2", _best([d.af2_pdockq2 for d in ranked]), ".3f", None),
        chip("best hotspot", _best([d.hotspot_satisfaction for d in ranked]), ".0%", _GATE["hotspot"]),
        chip("best BSA Å²", _best([d.interface_bsa for d in ranked]), ".0f", _GATE["bsa"]),
        chip("max contacts", _best([_f(d.n_interface_contacts) for d in ranked]), ".0f", None),
        chip("min clash", _best([d.clash_score for d in ranked], lower_is_better=True), ".1f", None, lower=True),
        chip("best ESM", _best([d.esm_monomer_plddt for d in ranked]), ".1f", None),
    ]
    return (
        '<div class="metric-suite"><div class="metric-suite-label">'
        f'best of {n} ranked · strict hit gate</div>'
        f'<div class="metrics">{"".join(chips)}</div></div>'
    )


def _f(v: Optional[int]) -> Optional[float]:
    return None if v is None else float(v)


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
  <h2>Candidates <span class="muted">({len(ranked)} ranked, by AF2 complex pLDDT;
    <span class="hit-key">hit</span> = clears strict gate)</span></h2>
  <table class="candidates">
    <thead>
      <tr>
        <th>#</th>
        <th>hit</th>
        <th>pLDDT</th>
        <th>ipSAE</th>
        <th>ipTM</th>
        <th>pDockQ</th>
        <th>pDockQ2</th>
        <th>hotspot</th>
        <th>BSA Å²</th>
        <th>contacts</th>
        <th>clash</th>
        <th>ESM</th>
        <th>len</th>
        <th>sequence</th>
        <th>PDB</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _cell(value: Optional[float], fmt: str, thr: Optional[float],
          *, ge: bool = True, lower: bool = False) -> str:
    """A numeric table cell, colour-coded pass/fail against a gate threshold
    (no colour when ``thr`` is None or the value is missing)."""
    if value is None:
        return '<td class="num muted">—</td>'
    txt = format(value, fmt)
    if thr is None:
        return f'<td class="num">{txt}</td>'
    ok = (value <= thr if lower else (value >= thr if ge else value > thr))
    return f'<td class="num {"cell-ok" if ok else "cell-bad"}">{txt}</td>'


def _render_row(d: DesignRecord) -> str:
    hit = _is_hit(d)
    hit_cell = (
        '<td class="num cell-ok">✓</td>' if hit else '<td class="num cell-bad">✗</td>'
    )
    seq_clean = (d.sequence or "").replace("/", "")
    pdb_link = (
        f'<a href="{html.escape(d.af2_complex_pdb)}">⬇</a>'
        if d.af2_complex_pdb
        else "—"
    )
    msa_warn = ' <span class="warn-tag">MSA degraded</span>' if d.msa_degraded else ""
    plddt = _cell(d.af2_complex_plddt, ".1f", _GATE["plddt"], ge=False)
    # splice the MSA-degraded tag into the pLDDT cell
    plddt = plddt.replace("</td>", f"{msa_warn}</td>", 1)
    return f"""
<tr>
  <td class="rank">{d.rank if d.rank is not None else "—"}</td>
  {hit_cell}
  {plddt}
  {_cell(d.af2_ipsae, ".3f", _GATE["ipsae"])}
  {_cell(d.af2_iptm, ".3f", _GATE["iptm"])}
  {_cell(d.af2_pdockq, ".3f", None)}
  {_cell(d.af2_pdockq2, ".3f", None)}
  {_cell(d.hotspot_satisfaction, ".0%", _GATE["hotspot"])}
  {_cell(d.interface_bsa, ".0f", _GATE["bsa"])}
  {_cell(_f(d.n_interface_contacts), ".0f", None)}
  {_cell(d.clash_score, ".1f", None)}
  {_cell(d.esm_monomer_plddt, ".1f", None)}
  <td class="num">{d.binder_length}</td>
  <td class="seq"><code>{html.escape(seq_clean)}</code></td>
  <td class="pdb">{pdb_link}</td>
</tr>
"""


def _render_activity(activity: list[dict[str, str]], skill_edits: list[str]) -> str:
    """Structured 'what the agent did' section: a Skills-evolved block (self-
    evolution) + a timeline of debate scouts, pipeline tool calls, and skill
    edits. Complements the prose 'Agent reasoning' panel below it."""
    parts: list[str] = []
    if skill_edits:
        items = "".join(f"<li><code>{html.escape(str(p))}</code></li>" for p in skill_edits)
        parts.append(
            '<div class="evolved-block"><h3>🧬 Skills evolved this run</h3>'
            f"<ul>{items}</ul></div>"
        )
    rows: list[str] = []
    for ev in activity:
        kind = ev.get("kind", "")
        rows.append(
            f'<li class="act act-{html.escape(kind)}">'
            f'<span class="act-kind">{html.escape(kind)}</span> '
            f'{html.escape(ev.get("label", ""))}</li>'
        )
    timeline = (
        f'<ol class="timeline">{"".join(rows)}</ol>'
        if rows
        else '<p class="muted">No structured activity captured.</p>'
    )
    return f"""
<section class="card">
  <h2>Run activity <span class="muted">(debate · pipeline · self-evolution)</span></h2>
  {"".join(parts)}
  {timeline}
</section>
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


def _render_plan(plan_text: str) -> str:
    """Inline ``plan.md`` — the agent's notebook: scout hypotheses, the
    debate (challenge → defend/revise), and the converged design hypothesis.
    This is where the actual debate *substance* lives (the activity timeline
    only shows scout titles). Rendered verbatim, so it stays honest."""
    plan_text = (plan_text or "").strip()
    if not plan_text or plan_text.startswith("# Plan\n\nThe Claude agent"):
        # the untouched seed template → the agent never wrote a real plan
        return (
            '<section class="card"><h2>Plan &amp; debate</h2>'
            '<p class="muted">No plan written — the agent never reached the '
            "deliberation/debate stage this run (plan.md is the seed template)."
            "</p></section>"
        )
    return f"""
<section class="card">
  <h2>Plan &amp; debate <span class="muted">(plan.md — scouts · challenge/defend · converged hypothesis)</span></h2>
  <pre class="plan-md">{html.escape(plan_text)}</pre>
</section>
"""


def _render_trace(events: list[dict[str, Any]]) -> str:
    """The 'Raw trace' tab: every trace.jsonl event, type-filterable client-
    side. Events are inlined as JSON and rendered by a tiny script so the user
    can filter by type without leaving the report."""
    if not events:
        return (
            '<section class="card"><h2>Raw trace</h2>'
            '<p class="muted">No trace events captured.</p></section>'
        )
    kinds = sorted({str(e.get("type", "?")) for e in events})
    chips = "".join(
        f'<button class="trace-filter" data-kind="{html.escape(k)}">{html.escape(k)}</button>'
        for k in kinds
    )
    data = json.dumps(events)
    return f"""
<section class="card">
  <h2>Raw trace <span class="muted">({len(events)} events from trace.jsonl)</span></h2>
  <div class="trace-controls">
    <button class="trace-filter trace-active" data-kind="*">all</button>{chips}
  </div>
  <div id="trace-log" class="trace-log"></div>
  <script>const TRACE_EVENTS={data};
function _renderTrace(filter) {{
  const box = document.getElementById("trace-log");
  box.innerHTML = "";
  TRACE_EVENTS.forEach((ev, i) => {{
    const kind = (ev.type || "?");
    if (filter !== "*" && kind !== filter) return;
    const row = document.createElement("div");
    row.className = "trace-row trace-" + kind.replace(/[^a-z0-9_-]/gi, "");
    const head = document.createElement("div");
    head.className = "trace-head";
    let hint = ev.name || ev.subagent_type || "";
    if (ev.description) hint += " — " + ev.description;
    head.textContent = "#" + i + "  " + kind + (hint ? "  ·  " + hint : "");
    const pre = document.createElement("pre");
    pre.className = "trace-body";
    pre.textContent = JSON.stringify(ev, null, 2);
    row.appendChild(head); row.appendChild(pre);
    head.addEventListener("click", () => row.classList.toggle("trace-open"));
    box.appendChild(row);
  }});
}}
document.querySelectorAll(".trace-filter").forEach(b => b.addEventListener("click", () => {{
  document.querySelectorAll(".trace-filter").forEach(x => x.classList.remove("trace-active"));
  b.classList.add("trace-active");
  _renderTrace(b.dataset.kind);
}}));
_renderTrace("*");</script>
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

/* Metric suite (best-of + hit gate) */
.metric-suite { margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--border); }
.metric-suite-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--fg-muted); margin-bottom: 8px; }
.metrics { display: flex; gap: 8px; flex-wrap: wrap; }
.metric { display: flex; flex-direction: column; gap: 2px; padding: 6px 10px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--bg); }
.metric-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--fg-muted); }
.metric-value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric-thr { font-size: 10px; font-weight: 500; color: var(--fg-dim); }
.metric-ok { border-color: #86efac; background: #f0fdf4; }
.metric-ok .metric-value { color: #15803d; }
.metric-bad { border-color: #fca5a5; background: #fef2f2; }
.metric-bad .metric-value { color: #b91c1c; }
.cell-ok { color: #15803d; font-weight: 600; }
.cell-bad { color: #b91c1c; }
.hit-key { color: #15803d; font-weight: 600; }

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
table.candidates th, table.candidates td { padding: 6px 8px; text-align: left;
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
.evolved-block { margin: 0 0 14px; padding: 10px 12px; background: var(--bg);
  border-left: 3px solid #7c3aed; border-radius: 4px; }
.evolved-block h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; }
.evolved-block ul { margin: 0; padding-left: 20px; font-size: 13px; }
.timeline { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.timeline .act { padding: 6px 0; border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere; }
.timeline .act:last-child { border-bottom: none; }
.act-kind { display: inline-block; min-width: 64px; margin-right: 8px; font-size: 10px;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--fg-muted); }
.act-debate .act-kind { color: #2563eb; }
.act-pipeline .act-kind { color: #059669; }
.act-skill { background: rgba(124,58,237,0.08); }
.act-skill .act-kind { color: #7c3aed; }

/* Plan & debate (inlined plan.md) */
.plan-md { white-space: pre-wrap; margin: 0; padding: 14px; background: var(--bg);
  border: 1px solid var(--border); border-radius: 8px; max-height: 560px; overflow: auto;
  font: 12.5px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-wrap: anywhere; }

/* Tabs */
.tabs { display: flex; gap: 4px; }
.tab-btn { font: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
  padding: 8px 16px; border: 1px solid var(--border); border-bottom: none;
  background: var(--bg); color: var(--fg-muted); border-radius: 8px 8px 0 0; }
.tab-btn.tab-active { background: var(--bg-card); color: var(--accent); }
.tab-panel { display: flex; flex-direction: column; gap: 20px; }
.tab-panel[hidden] { display: none; }

/* Raw trace */
.trace-controls { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.trace-filter { font: inherit; font-size: 12px; cursor: pointer; padding: 3px 10px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--fg-muted); }
.trace-filter.trace-active { background: var(--accent); color: #fff; border-color: var(--accent); }
.trace-log { max-height: 640px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
.trace-row { border-bottom: 1px solid var(--border); }
.trace-row:last-child { border-bottom: none; }
.trace-head { padding: 7px 10px; cursor: pointer; font: 12px/1.4 ui-monospace, Menlo, Consolas, monospace;
  color: var(--fg); background: var(--bg); }
.trace-head:hover { background: #eef2f7; }
.trace-body { display: none; margin: 0; padding: 10px 12px; background: #0f172a; color: #e2e8f0;
  font: 11.5px/1.5 ui-monospace, Menlo, Consolas, monospace; overflow-x: auto;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.trace-row.trace-open .trace-body { display: block; }
.trace-tool_use .trace-head { color: #047857; }
.trace-subagent_spawn .trace-head { color: #2563eb; }
.trace-assistant_text .trace-head, .trace-assistant_thinking .trace-head { color: #7c3aed; }

@media (max-width: 720px) {
  main { padding: 14px; }
  .viewer { height: 380px; }
  table.candidates td.seq { display: none; }
}
"""

_TAB_JS = """
document.querySelectorAll(".tab-btn").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".tab-btn").forEach(x => x.classList.remove("tab-active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.hidden = true);
  b.classList.add("tab-active");
  document.getElementById(b.dataset.tab).hidden = false;
}));
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
    <nav class="tabs">
      <button class="tab-btn tab-active" data-tab="tab-report">Design report</button>
      <button class="tab-btn" data-tab="tab-trace">Raw trace</button>
    </nav>
    <div id="tab-report" class="tab-panel">
      {viewer}
      {candidates}
      {activity}
      {plan}
      {reasoning}
    </div>
    <div id="tab-trace" class="tab-panel" hidden>
      {trace}
    </div>
  </main>
  <script>{script}</script>
</body>
</html>
"""


__all__ = ["render_report"]

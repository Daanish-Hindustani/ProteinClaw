"""Post-run triage: parse trace.jsonl → ranked design list + result.json.

Reads the per-run ``trace.jsonl`` and reconstructs the campaign's design
records by joining:
  * RFD3 backbones (each ``design.rfdiffusion3`` call returns N paths)
  * MPNN sequences (each ``design.proteinmpnn`` call returns sequences[])
  * ESMFold monomer pLDDT (one ``structure.esmfold`` call returns
    ``predictions[]`` keyed by sequence)
  * AF2-multimer complex pLDDT (one call per surviving sequence,
    returns ``complex_confidence`` — first-pass ranking signal)
  * AF-M screen score (5-model confirmation, when present, final nanobody ranker)

Ranking signal is ``afm_combo_feature`` for nanobody designs when available,
otherwise ``af2_complex_plddt`` (high → low). Designs without AF2 results are
listed unranked at the bottom.

Side effects:
  * Writes ``<output_dir>/result.json``
  * Copies the top AF2 complex PDBs into ``<output_dir>/designs/rank_NN_<id>.pdb``
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# trace event helpers
# ---------------------------------------------------------------------------

# The MCP tool name flattens `<category>.<tool>` to `<category>_<tool>`; the
# SDK wraps that with `proteinclaw_`.
_MCP_PREFIX = "proteinclaw_"


def _tool_short(name: str) -> str:
    if name.startswith(_MCP_PREFIX):
        return name[len(_MCP_PREFIX):]
    return name


def _iter_events(trace_path: Path) -> Iterable[dict[str, Any]]:
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _parse_tool_result_envelope(content: Any) -> Optional[dict[str, Any]]:
    """Best-effort extraction of the JSON envelope a tool returns.

    The MCP transport packages it as a content list of text blocks. We try
    to parse the concatenated text as JSON; if that fails, return None.
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text += str(item.get("text", ""))
            elif isinstance(item, str):
                text += item
        if not text:
            return None
    else:
        return None
    text = text.strip()
    # Some envelopes are wrapped in code fences from the wrapper; tolerate.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").rstrip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# in-memory record types
# ---------------------------------------------------------------------------


@dataclass
class TargetInfo:
    pdb_id: Optional[str] = None
    chain: Optional[str] = None
    crop: Optional[str] = None
    title: Optional[str] = None
    # RFdiffusion3 hotspot spec the agent designed against (e.g. "A56,A115"),
    # in the ORIGINAL target numbering — used for hotspot satisfaction.
    hotspots: Optional[str] = None


@dataclass
class DesignRecord:
    sequence: str
    binder_length: int
    esm_monomer_plddt: Optional[float] = None
    esm_monomer_pdb: Optional[str] = None
    af2_complex_plddt: Optional[float] = None
    af2_complex_pdb: Optional[str] = None
    af2_target_plddt: Optional[float] = None
    # ipSAE interface metrics (Dunbrack ipsae.py) — supplementary to the
    # complex_plddt ranking signal; surfaced for the agent/report to weigh.
    af2_ipsae: Optional[float] = None
    af2_iptm: Optional[float] = None
    af2_pdockq: Optional[float] = None
    af2_pdockq2: Optional[float] = None
    af2_ipsae_d0chn: Optional[float] = None
    af2_lis: Optional[float] = None
    af2_out_folder: Optional[str] = None
    # 5-model AF-M screen confirmation metrics (analysis.afm_screen_score).
    afm_combo_feature: Optional[float] = None
    afm_avg_model_support: Optional[float] = None
    afm_n_unique_contacts: Optional[int] = None
    afm_avg_interface_pae: Optional[float] = None
    afm_avg_interface_plddt: Optional[float] = None
    afm_avg_iptm: Optional[float] = None
    afm_avg_rtm: Optional[float] = None
    afm_avg_pdockq: Optional[float] = None
    # Deterministic interface QC (analysis.compute_interface_metrics) — augment,
    # not replace, the complex_plddt ranking. None when not computed/failed.
    hotspot_satisfaction: Optional[float] = None
    n_interface_contacts: Optional[int] = None
    interface_bsa: Optional[float] = None
    clash_score: Optional[float] = None
    n_iface_res_binder: Optional[int] = None
    n_iface_res_target: Optional[int] = None
    # Nanobody-specific (None for mini-binders). binder_type selects the hit gate.
    binder_type: str = "minibinder"
    framework: Optional[str] = None
    cdr3_seq: Optional[str] = None
    interface_plddt: Optional[float] = None
    h3_plddt: Optional[float] = None
    cdr_contact_fraction: Optional[float] = None
    # Predicted binding affinity (PRODIGY) — ADVISORY, never gating.
    predicted_kd_nm: Optional[float] = None
    predicted_dg: Optional[float] = None
    msa_degraded: bool = False
    rank: Optional[int] = None
    # `source` records which RFD3 backbone / MPNN call produced this sequence;
    # we don't always know with certainty, so it's optional.
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriageResult:
    target: TargetInfo
    designs: list[DesignRecord]
    esm_threshold_used: Optional[float] = None
    ranking_signal: str = "af2_complex_plddt"
    notes: list[str] = field(default_factory=list)
    # sequence → {cdr1,cdr2,cdr3,framework,cdr3_seq} from a nanobody_library
    # call. Used to compute CDR-aware metrics; not serialized into result.json.
    cdr_index: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ranked_designs(self) -> list[DesignRecord]:
        ranked = [d for d in self.designs if d.af2_complex_plddt is not None]
        ranked.sort(key=_rank_key, reverse=True)
        return ranked

    @property
    def unranked_designs(self) -> list[DesignRecord]:
        return [d for d in self.designs if d.af2_complex_plddt is None]

    def to_dict(self) -> dict[str, Any]:
        combo_present = any(d.afm_combo_feature is not None for d in self.designs)
        designs = []
        for i, d in enumerate(self.ranked_designs, start=1):
            d.rank = i
            designs.append(asdict(d))
        for d in self.unranked_designs:
            designs.append(asdict(d))
        return {
            "target": asdict(self.target),
            "ranking_signal": "afm_combo_feature_then_af2_complex_plddt"
            if combo_present
            else self.ranking_signal,
            "esm_threshold_used": self.esm_threshold_used,
            "num_designs": len(self.designs),
            "num_ranked": len(self.ranked_designs),
            "designs": designs,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def parse_trace(trace_path: Path) -> TriageResult:
    """Walk the trace and build a ``TriageResult``."""
    target = TargetInfo()
    designs_by_seq: dict[str, DesignRecord] = {}
    notes: list[str] = []
    cdr_index: dict[str, dict[str, Any]] = {}
    esm_threshold: Optional[float] = None

    # Map tool_use_id → (short tool name, input args) so we can join results.
    pending: dict[str, tuple[str, dict[str, Any]]] = {}

    for ev in _iter_events(trace_path):
        etype = ev.get("type")
        if etype == "tool_use":
            short = _tool_short(ev.get("name", ""))
            pending[ev.get("tool_use_id", "")] = (short, ev.get("input") or {})
        elif etype == "tool_result":
            tid = ev.get("tool_use_id", "")
            if tid not in pending:
                continue
            short, args = pending.pop(tid)
            env = _parse_tool_result_envelope(ev.get("content"))
            if env is None:
                continue
            _absorb(short, args, env, target, designs_by_seq, notes, cdr_index)
        elif etype == "assistant_text":
            # Cheap heuristic: look for an explicit ESMFold threshold mention.
            text = ev.get("text", "")
            m = re.search(
                r"esm[- ]?fold.{0,60}?(?:threshold|cutoff)[^\d]{0,12}(\d{2,3}(?:\.\d+)?)",
                text,
                re.IGNORECASE,
            )
            if m:
                try:
                    esm_threshold = float(m.group(1))
                except ValueError:
                    pass

    return TriageResult(
        target=target,
        designs=list(designs_by_seq.values()),
        esm_threshold_used=esm_threshold,
        notes=notes,
        cdr_index=cdr_index,
    )


def _absorb(
    short: str,
    args: dict[str, Any],
    env: dict[str, Any],
    target: TargetInfo,
    designs: dict[str, DesignRecord],
    notes: list[str],
    cdr_index: Optional[dict[str, dict[str, Any]]] = None,
) -> None:
    """Fold one tool result into the in-progress triage state."""
    if cdr_index is None:
        cdr_index = {}

    if short == "design_nanobody_library":
        # Read the library manifest off disk to recover per-sequence CDR ranges
        # (the envelope returns paths, not sequences). Used downstream for the
        # CDR-aware interface metrics + the nanobody hit gate.
        jpath = env.get("library_json_path")
        if not jpath or not Path(jpath).exists():
            return
        try:
            data = json.loads(Path(jpath).read_text())
        except (OSError, ValueError) as exc:
            notes.append(f"could not read nanobody library.json: {exc}")
            return
        framework = data.get("framework")
        for rec in data.get("designs") or []:
            seq = rec.get("sequence")
            if not isinstance(seq, str) or not seq:
                continue
            cdr_index[seq] = {
                "cdr1": rec.get("cdr1"),
                "cdr2": rec.get("cdr2"),
                "cdr3": rec.get("cdr3"),
                "framework": framework,
                "cdr3_seq": rec.get("cdr3_seq"),
            }
        return

    if short == "data_pdb_fetch":
        pid = env.get("pdb_id") or args.get("pdb_id")
        if not pid:
            return
        pid_upper = str(pid).upper()
        # First fetch wins for the canonical pdb_id. Later fetches contribute
        # chain/crop info if the first call didn't have them (common pattern:
        # agent calls pdb_fetch once with no chain to inspect, then again
        # with explicit chain+crop).
        if target.pdb_id is None:
            target.pdb_id = pid_upper
        if target.pdb_id == pid_upper:
            new_chain = env.get("chain") or args.get("chain")
            new_crop = env.get("crop") or args.get("crop")
            if new_chain and target.chain is None:
                target.chain = new_chain
            if new_crop and target.crop is None:
                target.crop = new_crop
        return

    if short == "data_rcsb_search":
        cands = env.get("candidates") or []
        if cands and target.title is None:
            target.title = cands[0].get("title")
        return

    if short == "design_rfdiffusion3":
        # Capture the hotspot spec the agent designed against (run-level) for
        # hotspot-satisfaction scoring. First RFD3 call wins.
        hs = args.get("hotspot_residues")
        if hs and target.hotspots is None:
            target.hotspots = hs if isinstance(hs, str) else ",".join(map(str, hs))
        return

    if short == "design_proteinmpnn":
        for seq in env.get("sequences") or []:
            if not isinstance(seq, str) or not seq:
                continue
            # Keep a single record per sequence; first call wins for source.
            if seq not in designs:
                designs[seq] = DesignRecord(
                    sequence=seq,
                    binder_length=len(seq.replace("/", "")),
                    source={"mpnn_backbone": args.get("backbone_pdb")},
                )
        return

    if short == "structure_esmfold":
        for pred in env.get("predictions") or []:
            seq = pred.get("sequence")
            if not isinstance(seq, str):
                continue
            rec = designs.setdefault(
                seq,
                DesignRecord(sequence=seq, binder_length=pred.get("num_residues", 0)),
            )
            rec.esm_monomer_plddt = pred.get("confidence")
            rec.esm_monomer_pdb = pred.get("pdb_path")
        return

    if short == "structure_alphafold2_multimer":
        seq = args.get("binder_sequence")
        if not isinstance(seq, str) or "error" in env:
            if "error" in env:
                notes.append(
                    f"AF2 failed for binder {((seq or '')[:20])!r}: {env.get('summary')}"
                )
            return
        rec = designs.setdefault(
            seq,
            DesignRecord(sequence=seq, binder_length=len(seq)),
        )
        rec.af2_complex_plddt = env.get("complex_confidence")
        rec.af2_complex_pdb = env.get("complex_pdb_path")
        rec.af2_target_plddt = env.get("target_chain_plddt")
        rec.af2_ipsae = env.get("ipsae")
        rec.af2_ipsae_d0chn = env.get("ipsae_d0chn")
        rec.af2_iptm = env.get("iptm")
        rec.af2_pdockq = env.get("pdockq")
        rec.af2_pdockq2 = env.get("pdockq2")
        rec.af2_lis = env.get("lis")
        rec.af2_out_folder = env.get("out_folder")
        rec.msa_degraded = bool(env.get("msa_degraded", False))
        # Mark nanobody designs from the library index so the gate + CDR metrics apply.
        info = cdr_index.get(seq)
        if info is not None:
            rec.binder_type = "nanobody"
            rec.framework = info.get("framework")
            rec.cdr3_seq = info.get("cdr3_seq")
        return

    if short == "analysis_afm_screen_score":
        output_dir = str(env.get("output_dir") or args.get("output_dir") or "")
        rec = next(
            (d for d in designs.values() if d.af2_out_folder and Path(d.af2_out_folder).resolve() == Path(output_dir).resolve()),
            None,
        )
        if rec is None:
            notes.append(f"AF-M screen score could not be matched to a design: {output_dir}")
            return
        avg = env.get("avg_metrics") or {}
        rec.afm_combo_feature = env.get("combo_feature")
        rec.afm_avg_model_support = env.get("avg_model_support")
        rec.afm_n_unique_contacts = env.get("n_unique_contacts")
        rec.afm_avg_interface_pae = avg.get("avg_interface_pae")
        rec.afm_avg_interface_plddt = avg.get("avg_interface_plddt")
        rec.afm_avg_iptm = avg.get("iptm")
        rec.afm_avg_rtm = avg.get("rtm")
        rec.afm_avg_pdockq = avg.get("pdockq")
        return


def _rank_key(d: DesignRecord) -> tuple[float, float]:
    combo = d.afm_combo_feature if d.binder_type == "nanobody" else None
    return (
        combo if combo is not None else -1.0,
        d.af2_complex_plddt or 0.0,
    )


# ---------------------------------------------------------------------------
# side-effect helpers
# ---------------------------------------------------------------------------


def stage_ranked_designs(
    triage: TriageResult, designs_dir: Path
) -> list[DesignRecord]:
    """Copy each ranked design's AF2 PDB into ``designs/rank_NN_<id>.pdb``.

    Updates each record's ``af2_complex_pdb`` to the staged location so
    consumers (HTML report, downstream pipelines) have stable filenames.
    """
    designs_dir.mkdir(parents=True, exist_ok=True)
    staged: list[DesignRecord] = []
    for i, d in enumerate(triage.ranked_designs, start=1):
        d.rank = i
        if not d.af2_complex_pdb:
            continue
        src = Path(d.af2_complex_pdb)
        if not src.exists():
            continue
        # 6-char sequence preview gives a quick visual id without leaking
        # the whole sequence into the filename.
        short_id = d.sequence[:6]
        dst = designs_dir / f"rank_{i:02d}_{short_id}.pdb"
        try:
            shutil.copyfile(src, dst)
            d.af2_complex_pdb = str(dst)
            staged.append(d)
        except OSError:
            continue
    return staged


def _crop_start(crop: Optional[str]) -> Optional[int]:
    """'19-127' / '19' → 19 (first target residue of the crop)."""
    if not crop:
        return None
    m = re.match(r"\s*(\d+)", str(crop))
    return int(m.group(1)) if m else None


def annotate_interface_metrics(triage: TriageResult) -> None:
    """Populate deterministic interface QC on each ranked design that has a
    complex PDB on disk. Per-design failures degrade to ``None`` + a note —
    QC must never break triage. Call AFTER ``stage_ranked_designs`` (uses the
    staged complex path) and BEFORE ``write_result_json``.
    """
    from proteinclaw.analysis import compute_interface_metrics

    crop_start = _crop_start(triage.target.crop)
    hotspots = triage.target.hotspots
    for d in triage.ranked_designs:
        if not d.af2_complex_pdb or not Path(d.af2_complex_pdb).exists():
            continue
        # Nanobody designs carry CDR ranges in the library index → CDR-aware metrics.
        cdr_info = triage.cdr_index.get(d.sequence)
        cdr_ranges = (
            {k: cdr_info[k] for k in ("cdr1", "cdr2", "cdr3") if cdr_info.get(k)}
            if cdr_info
            else None
        )
        try:
            m = compute_interface_metrics(
                d.af2_complex_pdb, hotspots=hotspots, crop_start=crop_start,
                cdr_ranges=cdr_ranges,
            )
        except Exception as exc:  # noqa: BLE001 — QC must never break triage
            triage.notes.append(f"interface metrics failed (rank {d.rank}): {exc}")
            continue
        d.hotspot_satisfaction = m["hotspot_satisfaction"]
        d.n_interface_contacts = m["interface_contacts"]
        d.interface_bsa = m["interface_bsa"]
        d.clash_score = m["clash_score"]
        d.n_iface_res_binder = m["interface_residues_binder"]
        d.n_iface_res_target = m["interface_residues_target"]
        d.interface_plddt = m["interface_plddt"]
        d.h3_plddt = m["h3_plddt"]
        d.cdr_contact_fraction = m["cdr_contact_fraction"]
        # Advisory predicted KD/ΔG — nanobodies only (deliberately not for
        # mini-binders; contact-based KD is untrustworthy and was dropped there).
        if d.binder_type == "nanobody":
            _annotate_affinity(d, triage.notes)


def _annotate_affinity(d: DesignRecord, notes: list[str]) -> None:
    """Populate advisory predicted KD/ΔG (PRODIGY). Soft-fail to None + note."""
    try:
        from proteinclaw.tools.binding_affinity import binding_affinity

        out = binding_affinity(complex_pdb_path=d.af2_complex_pdb)
        d.predicted_kd_nm = out.get("predicted_kd_nm")
        d.predicted_dg = out.get("predicted_dg")
        if out.get("affinity_error"):
            notes.append(f"affinity (rank {d.rank}): {out['affinity_error']}")
    except Exception as exc:  # noqa: BLE001 — advisory, never breaks triage
        notes.append(f"affinity failed (rank {d.rank}): {exc}")


def write_result_json(
    triage: TriageResult,
    output_path: Path,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Write result.json from the triage. ``extra`` is merged into the
    top-level object (e.g. ``{"skill_edits": [...]}`` from the run summary)."""
    payload = triage.to_dict()
    if extra:
        payload.update(extra)
    output_path.write_text(
        json.dumps(payload, default=str, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "DesignRecord",
    "TargetInfo",
    "TriageResult",
    "parse_trace",
    "stage_ranked_designs",
    "annotate_interface_metrics",
    "write_result_json",
]

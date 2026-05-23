"""Post-run triage: parse trace.jsonl → ranked design list + result.json.

Reads the per-run ``trace.jsonl`` and reconstructs the campaign's design
records by joining:
  * RFD3 backbones (each ``design.rfdiffusion3`` call returns N paths)
  * MPNN sequences (each ``design.proteinmpnn`` call returns sequences[])
  * ESMFold monomer pLDDT (one ``structure.esmfold`` call returns
    ``predictions[]`` keyed by sequence)
  * AF2-multimer complex pLDDT (one call per surviving sequence,
    returns ``complex_confidence`` — THE ranking signal per PRD §6.6)

Ranking signal is ``af2_complex_plddt`` (high → low). Designs without
AF2 results are listed unranked at the bottom.

Side effects:
  * Writes ``<output_dir>/result.json``
  * Copies the top AF2 complex PDBs into ``<output_dir>/designs/rank_NN_<id>.pdb``
  * Populates the SQLite ``designs`` table for the run.
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
# SDK wraps that with `mcp__proteinclaw_tools__`.
_MCP_PREFIX = "mcp__proteinclaw_tools__"


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


@dataclass
class DesignRecord:
    sequence: str
    binder_length: int
    esm_monomer_plddt: Optional[float] = None
    esm_monomer_pdb: Optional[str] = None
    af2_complex_plddt: Optional[float] = None
    af2_complex_pdb: Optional[str] = None
    af2_target_plddt: Optional[float] = None
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

    @property
    def ranked_designs(self) -> list[DesignRecord]:
        ranked = [d for d in self.designs if d.af2_complex_plddt is not None]
        ranked.sort(key=lambda d: d.af2_complex_plddt or 0.0, reverse=True)
        return ranked

    @property
    def unranked_designs(self) -> list[DesignRecord]:
        return [d for d in self.designs if d.af2_complex_plddt is None]

    def to_dict(self) -> dict[str, Any]:
        designs = []
        for i, d in enumerate(self.ranked_designs, start=1):
            d.rank = i
            designs.append(asdict(d))
        for d in self.unranked_designs:
            designs.append(asdict(d))
        return {
            "target": asdict(self.target),
            "ranking_signal": self.ranking_signal,
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
            _absorb(short, args, env, target, designs_by_seq, notes)
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
    )


def _absorb(
    short: str,
    args: dict[str, Any],
    env: dict[str, Any],
    target: TargetInfo,
    designs: dict[str, DesignRecord],
    notes: list[str],
) -> None:
    """Fold one tool result into the in-progress triage state."""

    if short == "data_pdb_fetch":
        pid = env.get("pdb_id") or args.get("pdb_id")
        if pid and target.pdb_id is None:
            target.pdb_id = str(pid).upper()
            target.chain = env.get("chain") or args.get("chain")
            target.crop = env.get("crop") or args.get("crop")
        return

    if short == "data_rcsb_search":
        cands = env.get("candidates") or []
        if cands and target.title is None:
            target.title = cands[0].get("title")
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
        rec.msa_degraded = bool(env.get("msa_degraded", False))
        return


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


def write_result_json(triage: TriageResult, output_path: Path) -> None:
    output_path.write_text(
        json.dumps(triage.to_dict(), default=str, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "DesignRecord",
    "TargetInfo",
    "TriageResult",
    "parse_trace",
    "stage_ranked_designs",
    "write_result_json",
]

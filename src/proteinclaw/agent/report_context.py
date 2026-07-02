"""Trace parsing helpers used by MCP report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proteinclaw.agent.skills import plugin_skills_root


def _collect_reasoning(trace_path: Path) -> list[str]:
    """Pull assistant_text events from the trace, in order."""
    out: list[str] = []
    if not trace_path.exists():
        return out
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant_text":
                text = (ev.get("text") or "").strip()
                if text:
                    out.append(text)
    return out


_PIPELINE_TOOLS = {
    "design_rfdiffusion3",
    "design_proteinmpnn",
    "structure_esmfold",
    "structure_alphafold2_multimer",
    "analysis_interface_metrics",
}


def _activity_tool_label(short: str, inp: dict[str, Any]) -> str:
    if short == "design_rfdiffusion3":
        return (
            f"RFdiffusion3 - hotspots {inp.get('hotspot_residues', '?')}, "
            f"len {inp.get('binder_length', '?')}, n={inp.get('num_designs', '?')}"
        )
    if short == "design_proteinmpnn":
        return f"ProteinMPNN - {inp.get('num_sequences', '?')} seq/backbone, temp {inp.get('sampling_temp', '?')}"
    if short == "structure_esmfold":
        return f"ESMFold - {len(inp.get('sequences') or [])} sequences"
    if short == "structure_alphafold2_multimer":
        return f"AF2-multimer - binder {len(inp.get('binder_sequence') or '')} aa"
    if short == "analysis_interface_metrics":
        return "Interface metrics (QC)"
    return short


def _read_plan_md(plan_path: Path) -> str:
    try:
        return plan_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_TRACE_FIELD_CAP = 4000


def _collect_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    """Parse trace.jsonl, truncating over-long string fields."""

    def _trim(v: Any) -> Any:
        if isinstance(v, str) and len(v) > _TRACE_FIELD_CAP:
            return v[:_TRACE_FIELD_CAP] + f"... (+{len(v) - _TRACE_FIELD_CAP} chars)"
        if isinstance(v, dict):
            return {k: _trim(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_trim(x) for x in v]
        return v

    out: list[dict[str, Any]] = []
    if not trace_path.exists():
        return out
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                out.append(_trim(ev))
    return out


def _short_tool_name(name: str) -> str:
    prefix = "proteinclaw_"
    if name.startswith(prefix):
        return name[len(prefix):]
    return name.split("__")[-1]


def _collect_activity(trace_path: Path) -> list[dict[str, str]]:
    """Build a report timeline from native research/debate and pipeline calls."""
    skills_root = str(plugin_skills_root())
    out: list[dict[str, str]] = []
    if not trace_path.exists():
        return out
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "research_record":
                source = ev.get("source") or "native_web"
                query = (ev.get("query") or ev.get("summary") or "").strip()
                out.append({"kind": "debate", "label": f"research/{source}: {query}" if query else f"research/{source}"})
            elif t == "debate_record":
                st = ev.get("subagent_type") or "native_subagent"
                desc = (ev.get("summary") or ev.get("prompt") or "").strip()
                out.append({"kind": "debate", "label": f"{st}: {desc}" if desc else st})
            elif t == "subagent_spawn":
                st = ev.get("subagent_type") or "research"
                desc = (ev.get("description") or "").strip()
                out.append({"kind": "debate", "label": f"{st}: {desc}" if desc else st})
            elif t == "tool_use":
                name = str(ev.get("name") or "")
                inp = ev.get("input") or {}
                if name in {
                    "proteinclaw_skill_append",
                    "proteinclaw_skill_create",
                    "proteinclaw_skill_write",
                    "proteinclaw_skill_patch",
                    "proteinclaw_skill_delete",
                }:
                    skill = inp.get("skill") or inp.get("name") or "proteinclaw"
                    action = name.rsplit("_", 1)[-1]
                    out.append({"kind": "skill", "label": f"plugin skill {action}: {skill}"})
                elif name in ("Write", "Edit", "file_write", "file_patch"):
                    fp = inp.get("file_path") or inp.get("path")
                    if not isinstance(fp, str):
                        continue
                    try:
                        rp = str(Path(fp).resolve())
                    except OSError:
                        rp = fp
                    if rp.startswith(skills_root):
                        label_path = rp[len(skills_root):].replace("\\", "/").lstrip("/")
                        verb = "created" if name in ("Write", "file_write") else "updated"
                        out.append({"kind": "skill", "label": f"skill {verb}: {label_path}"})
                else:
                    short = _short_tool_name(name)
                    if short in _PIPELINE_TOOLS:
                        out.append({"kind": "pipeline", "label": _activity_tool_label(short, inp)})
    return out


__all__ = [
    "_collect_activity",
    "_collect_reasoning",
    "_collect_trace_events",
    "_read_plan_md",
]

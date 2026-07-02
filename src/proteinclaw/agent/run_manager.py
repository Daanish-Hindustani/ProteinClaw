"""Run/session lifecycle for agent-native ProteinClaw MCP clients."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from proteinclaw.runner.local import DEFAULT_WORKSPACE_ROOT


@dataclass(frozen=True)
class RunContext:
    """Filesystem context for one ProteinClaw design run."""

    run_id: str
    session_id: str
    output_dir: Path
    workspace: Path
    trace_jsonl: Path
    plan_md: Path
    designs_dir: Path
    report_html: Path
    status: str = "created"
    prompt: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


class RunManager:
    """Owns run metadata independently of any CLI or model loop."""

    def __init__(
        self,
        *,
        runs_dir: Path | str = Path("./runs"),
        workspace_root: Path | str = DEFAULT_WORKSPACE_ROOT,
    ) -> None:
        self.runs_dir = Path(runs_dir).expanduser().resolve()
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        *,
        prompt: str = "",
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> RunContext:
        rid = run_id or uuid.uuid4().hex[:12]
        sid = session_id or rid
        if not _valid_id(rid) or not _valid_id(sid):
            raise ValueError("run_id and session_id must be alphanumeric plus ._-")
        now = time.time()
        ctx = self._context_for(
            run_id=rid,
            session_id=sid,
            prompt=prompt,
            status="created",
            created_at=now,
            updated_at=now,
        )
        ctx.output_dir.mkdir(parents=True, exist_ok=False)
        ctx.designs_dir.mkdir(parents=True, exist_ok=True)
        ctx.workspace.mkdir(parents=True, exist_ok=True)
        ctx.trace_jsonl.touch(exist_ok=True)
        self._write_meta(ctx)
        self.append_trace(ctx, {"type": "run_created", "prompt": prompt})
        return ctx

    def resume_run(self, run_id: str) -> RunContext:
        ctx = self.get_run(run_id)
        self.update_status(ctx.run_id, "running")
        return self.get_run(run_id)

    def finalize_run(self, run_id: str, *, status: str = "completed") -> RunContext:
        return self.update_status(run_id, status)

    def update_status(self, run_id: str, status: str) -> RunContext:
        ctx = self.get_run(run_id)
        updated = self._context_for(
            run_id=ctx.run_id,
            session_id=ctx.session_id,
            prompt=ctx.prompt,
            status=status,
            created_at=ctx.created_at,
            updated_at=time.time(),
        )
        self._write_meta(updated)
        self.append_trace(updated, {"type": "run_status", "status": status})
        return updated

    def get_run(self, run_id: str) -> RunContext:
        if not _valid_id(run_id):
            raise ValueError("invalid run_id")
        meta = self._meta_path(run_id)
        if not meta.exists():
            raise FileNotFoundError(f"ProteinClaw run {run_id!r} does not exist")
        data = json.loads(meta.read_text(encoding="utf-8"))
        return self._context_for(
            run_id=str(data["run_id"]),
            session_id=str(data["session_id"]),
            prompt=str(data.get("prompt") or ""),
            status=str(data.get("status") or "created"),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    def list_runs(self, *, limit: int = 50) -> list[RunContext]:
        contexts: list[RunContext] = []
        for meta in sorted(self.runs_dir.glob("*/run.json"), reverse=True):
            try:
                contexts.append(self.get_run(meta.parent.name))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if len(contexts) >= limit:
                break
        return contexts

    def append_trace(self, ctx: RunContext, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("ts", time.time())
        payload.setdefault("run_id", ctx.run_id)
        payload.setdefault("session_id", ctx.session_id)
        ctx.trace_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with ctx.trace_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")

    def _context_for(
        self,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        status: str,
        created_at: float,
        updated_at: float,
    ) -> RunContext:
        output_dir = self.runs_dir / run_id
        workspace = self.workspace_root / session_id
        return RunContext(
            run_id=run_id,
            session_id=session_id,
            output_dir=output_dir,
            workspace=workspace,
            trace_jsonl=output_dir / "trace.jsonl",
            plan_md=output_dir / "plan.md",
            designs_dir=output_dir / "designs",
            report_html=output_dir / "report.html",
            status=status,
            prompt=prompt,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _write_meta(self, ctx: RunContext) -> None:
        data = asdict(ctx)
        for key in ("output_dir", "workspace", "trace_jsonl", "plan_md", "designs_dir", "report_html"):
            data[key] = str(data[key])
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        self._meta_path(ctx.run_id).write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _meta_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "run.json"


def context_payload(ctx: RunContext) -> dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "session_id": ctx.session_id,
        "status": ctx.status,
        "prompt": ctx.prompt,
        "output_dir": str(ctx.output_dir),
        "workspace": str(ctx.workspace),
        "trace_jsonl": str(ctx.trace_jsonl),
        "plan_md": str(ctx.plan_md),
        "designs_dir": str(ctx.designs_dir),
        "report_html": str(ctx.report_html),
        "created_at": ctx.created_at,
        "updated_at": ctx.updated_at,
    }


def _valid_id(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in "._-" for ch in value)


__all__ = ["RunContext", "RunManager", "context_payload"]

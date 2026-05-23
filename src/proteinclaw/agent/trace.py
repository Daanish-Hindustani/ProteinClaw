"""``trace.jsonl`` writer — every agent step gets one line.

PRD §7: the trace is the reproducibility artifact. There is no ``--seed``;
what we keep is a complete, append-only log of every decision and tool
call. ``--show-reasoning`` (Phase 6+ wiring) replays the same events to
stdout.

Each line is a single JSON object with at minimum ``ts`` and ``type``.
Type-specific fields are nested under matching keys so a downstream
consumer can pattern-match on ``type`` and ignore the rest.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class TraceWriter:
    """Append-only JSONL writer with a tiny convenience surface."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch the file early so consumers can tail it from t=0.
        self.path.touch(exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:  # noqa: BLE001 — best-effort on close
            pass

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.close()
        return False

    # --- generic ---------------------------------------------------------

    def write(self, **fields: Any) -> None:
        """Write one event. ``ts`` is auto-stamped if not provided."""
        if "ts" not in fields:
            fields["ts"] = time.time()
        line = json.dumps(fields, default=str, ensure_ascii=False)
        self._fh.write(line + "\n")
        self._fh.flush()

    # --- typed helpers ---------------------------------------------------

    def run_started(
        self,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        output_dir: str,
        model: Optional[str] = None,
        rounds: int = 1,
        max_designs: int = 0,
        skill_chars: int = 0,
        sdk_version: Optional[str] = None,
    ) -> None:
        self.write(
            type="run_started",
            run_id=run_id,
            session_id=session_id,
            prompt=prompt,
            output_dir=output_dir,
            model=model,
            rounds=rounds,
            max_designs=max_designs,
            skill_chars=skill_chars,
            sdk_version=sdk_version,
        )

    def assistant_text(self, text: str) -> None:
        self.write(type="assistant_text", text=text)

    def thinking(self, text: str) -> None:
        # Captured separately so a reader can quickly grep just decisions.
        self.write(type="assistant_thinking", text=text)

    def tool_use(self, *, tool_use_id: str, name: str, input: Any) -> None:
        self.write(type="tool_use", tool_use_id=tool_use_id, name=name, input=input)

    def tool_result(
        self,
        *,
        tool_use_id: str,
        is_error: Optional[bool],
        content: Any,
    ) -> None:
        # Trim very long string contents so the trace stays inspectable.
        trimmed = _shallow_trim(content)
        self.write(
            type="tool_result",
            tool_use_id=tool_use_id,
            is_error=bool(is_error),
            content=trimmed,
        )

    def run_completed(
        self,
        *,
        session_id: str,
        num_turns: int,
        total_cost_usd: Optional[float],
        duration_ms: Optional[int],
        elapsed_wall_s: float,
    ) -> None:
        self.write(
            type="run_completed",
            session_id=session_id,
            num_turns=num_turns,
            total_cost_usd=total_cost_usd,
            duration_ms=duration_ms,
            elapsed_wall_s=round(elapsed_wall_s, 3),
        )

    def run_failed(self, *, error: str, exception_type: str) -> None:
        self.write(type="run_failed", error=error, exception_type=exception_type)


def _shallow_trim(value: Any, max_chars: int = 4000) -> Any:
    """Shorten obvious long strings in tool-result envelopes so the trace
    file stays inspectable. PDB bytes etc. should never reach here (PRD
    §9.3), but we guard anyway."""
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...[truncated {len(value) - max_chars} chars]"
    if isinstance(value, list):
        return [_shallow_trim(v, max_chars) for v in value]
    if isinstance(value, dict):
        return {k: _shallow_trim(v, max_chars) for k, v in value.items()}
    return value


__all__ = ["TraceWriter"]

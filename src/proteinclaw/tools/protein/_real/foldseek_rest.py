"""Foldseek REST backend.

Uses the public Foldseek server at https://search.foldseek.com which
exposes a ticket-based async API:

1. POST /api/ticket — submit a structure file, receive a ticket id.
2. GET /api/ticket/{id} — poll until status == "COMPLETE".
3. GET /api/result/{id}/0 — fetch results (the "0" is the database index).

This wrapper hides the polling and turns the response into our typed
`FoldseekOutputs`. The polling cap and interval are conservative — the
public server is rate-limited; long queries should run locally instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein.foldseek import (
    FoldseekBackend,
    FoldseekHit,
    FoldseekInputs,
    FoldseekOutputs,
)

_DEFAULT_URL = "https://search.foldseek.com"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 5.0
_POLL_MAX_ATTEMPTS = 60  # 5 min cap


class FoldseekRestBackend:
    """Foldseek REST client.

    Submit-and-poll lifecycle is hidden inside `search()`. The bound
    `database` parameter on the input determines which Foldseek DB the
    server queries; for the public server "pdb100" or "afdb50" are common.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = _DEFAULT_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
        max_attempts: int = _POLL_MAX_ATTEMPTS,
    ) -> None:
        """Bind an httpx client + polling parameters."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._base = base_url.rstrip("/")
        self._poll_interval = poll_interval_seconds
        self._max_attempts = max_attempts

    async def search(self, inputs: FoldseekInputs) -> FoldseekOutputs:
        """Submit a query and return ranked hits.

        Raises:
            ToolExecutionError: For network failures, missing query files,
                or polling timeouts.
        """
        path = Path(inputs.query_pdb_path)
        if not path.is_file():  # noqa: ASYNC240 — cheap stat at submit time
            raise ToolExecutionError("foldseek", f"query PDB not found: {inputs.query_pdb_path}")
        ticket_id = await self._submit(path, inputs.database)
        await self._wait_for_complete(ticket_id)
        hits = await self._fetch_results(ticket_id, inputs.max_hits)
        return FoldseekOutputs(hits=hits)

    async def _submit(self, query_path: Path, database: str) -> str:
        """POST the query and return the ticket id."""
        files = {"q": (query_path.name, query_path.read_bytes(), "chemical/x-pdb")}  # noqa: ASYNC240 — small file read
        data = {"database[]": database, "mode": "3diaa"}
        try:
            resp = await self._client.post(f"{self._base}/api/ticket", data=data, files=files)
        except httpx.RequestError as e:
            raise ToolExecutionError(
                "foldseek", f"network error submitting Foldseek ticket: {e}"
            ) from e
        if resp.status_code >= 400:
            raise ToolExecutionError(
                "foldseek",
                f"Foldseek submit returned {resp.status_code}: {resp.text[:200]}",
            )
        body = resp.json()
        ticket_id = body.get("id")
        if not isinstance(ticket_id, str):
            raise ToolExecutionError("foldseek", f"unexpected ticket response: {body}")
        return ticket_id

    async def _wait_for_complete(self, ticket_id: str) -> None:
        """Poll the ticket endpoint until status == COMPLETE."""
        for _ in range(self._max_attempts):
            try:
                resp = await self._client.get(f"{self._base}/api/ticket/{ticket_id}")
            except httpx.RequestError as e:
                raise ToolExecutionError("foldseek", f"network error polling ticket: {e}") from e
            if resp.status_code >= 400:
                raise ToolExecutionError(
                    "foldseek",
                    f"Foldseek poll returned {resp.status_code}: {resp.text[:200]}",
                )
            status = resp.json().get("status")
            if status == "COMPLETE":
                return
            if status == "ERROR":
                raise ToolExecutionError(
                    "foldseek", f"Foldseek server reported ERROR for ticket {ticket_id}"
                )
            await asyncio.sleep(self._poll_interval)
        raise ToolExecutionError(
            "foldseek",
            f"Foldseek polling timed out after {self._max_attempts} attempts",
        )

    async def _fetch_results(self, ticket_id: str, max_hits: int) -> tuple[FoldseekHit, ...]:
        """GET the result page and parse the top `max_hits` rows."""
        try:
            resp = await self._client.get(f"{self._base}/api/result/{ticket_id}/0")
        except httpx.RequestError as e:
            raise ToolExecutionError("foldseek", f"network error fetching results: {e}") from e
        if resp.status_code >= 400:
            raise ToolExecutionError(
                "foldseek",
                f"Foldseek result returned {resp.status_code}: {resp.text[:200]}",
            )
        body = resp.json()
        results = body.get("results", [])
        rows: list[dict[str, Any]] = []
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                alignments = first.get("alignments", [])
                if isinstance(alignments, list):
                    rows = [a for a in alignments if isinstance(a, dict)]
        rows.sort(key=lambda r: float(r.get("tm_score", 0.0)), reverse=True)
        rows = rows[:max_hits]
        return tuple(
            FoldseekHit(
                pdb_id=str(r.get("target", "?"))[:8],
                tm_score=float(r.get("tm_score", 0.0)),
                evalue=float(r.get("eval", 1.0)),
            )
            for r in rows
        )

    async def aclose(self) -> None:
        """Close the bound httpx client if we created it."""
        if self._owns_client:
            await self._client.aclose()


_: type[FoldseekBackend] = FoldseekRestBackend

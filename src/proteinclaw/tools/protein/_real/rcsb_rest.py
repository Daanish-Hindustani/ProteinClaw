"""Real RCSB REST backend.

Uses RCSB's public Data API (https://data.rcsb.org/). No credentials
required. Endpoints used:

- ``/rest/v1/core/entry/{pdb_id}`` — top-level metadata (organism via
  citation/source, length).
- ``/rest/v1/core/polymer_entity/{pdb_id}/{entity_id}`` — sequence + organism.

We hit `polymer_entity/.../1` first (the convention for the canonical
chain) and fall back to entry metadata if the entity request fails.
"""

from __future__ import annotations

import httpx

from proteinclaw.tools.base_tool import ToolExecutionError
from proteinclaw.tools.protein.rcsb import RCSBBackend, RCSBInputs, RCSBOutputs

_BASE_URL = "https://data.rcsb.org/rest/v1"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class RcsbRestBackend:
    """RCSB Data API client.

    Construct once per session — `httpx.AsyncClient` reuses connections.
    Pass a custom client for tests that need to mock the transport.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = _BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Bind an httpx client; create one with a sensible timeout if absent."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._base = base_url.rstrip("/")

    async def fetch(self, inputs: RCSBInputs) -> RCSBOutputs:
        """Fetch sequence and organism for `inputs.pdb_id` from RCSB.

        Raises:
            ToolExecutionError: When the API returns non-2xx, the entity
                payload lacks the expected fields, or the network call
                fails outright.
        """
        url = f"{self._base}/core/polymer_entity/{inputs.pdb_id}/1"
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as e:
            raise ToolExecutionError("rcsb", f"network error contacting RCSB: {e}") from e
        if resp.status_code == 404:
            raise ToolExecutionError("rcsb", f"PDB id not found: {inputs.pdb_id}")
        if resp.status_code >= 400:
            raise ToolExecutionError(
                "rcsb",
                f"RCSB returned {resp.status_code}: {resp.text[:200]}",
            )
        body = resp.json()
        sequence = _extract_sequence(body)
        organism = _extract_organism(body)
        if sequence is None:
            raise ToolExecutionError("rcsb", "RCSB response had no canonical sequence")
        return RCSBOutputs(
            pdb_id=inputs.pdb_id,
            sequence=sequence,
            length=len(sequence),
            organism=organism or "unknown",
        )

    async def aclose(self) -> None:
        """Close the bound httpx client if we created it."""
        if self._owns_client:
            await self._client.aclose()


def _extract_sequence(body: dict[str, object]) -> str | None:
    """Pull the one-letter sequence from a polymer_entity payload."""
    entity_poly = body.get("entity_poly")
    if isinstance(entity_poly, dict):
        seq = entity_poly.get("pdbx_seq_one_letter_code_can")
        if isinstance(seq, str) and seq:
            return seq.replace("\n", "").strip()
    return None


def _extract_organism(body: dict[str, object]) -> str | None:
    """Pull the source organism, preferring scientific name when available."""
    sources = body.get("rcsb_entity_source_organism")
    if isinstance(sources, list) and sources:
        first = sources[0]
        if isinstance(first, dict):
            name = first.get("scientific_name") or first.get("ncbi_scientific_name")
            if isinstance(name, str) and name:
                return name
    return None


# Compile-time assertion: the class satisfies the Protocol even though
# Python only checks at runtime via @runtime_checkable.
_: type[RCSBBackend] = RcsbRestBackend
